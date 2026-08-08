"""
双模型架构：梯度提升集成买入模型 + 梯度提升卖出模型

买入模型: CatBoost + LightGBM + XGBoost 线性加权集成
  预测: open(t+1) -> open(t+max_holding+1) 收益 >= label_threshold 的概率

卖出模型: CatBoost + LightGBM + XGBoost 线性加权集成
  预测次日上涨概率，持仓期间每日评估，概率极低时提前卖出

用户偏好: CatBoost优先，线性加权集成，可配置权重
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score
import joblib
from pathlib import Path

from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier

from utils import get_config, log
from factors import get_factor_columns

MODEL_PATH = Path(__file__).parent / "model.pkl"
EXIT_MODEL_PATH = Path(__file__).parent / "exit_model.pkl"


def _get_ensemble_weights():
    """从配置获取集成权重"""
    w = get_config("model.weights", {"catboost": 1.0, "lightgbm": 1.0, "xgboost": 1.0})
    total = w["catboost"] + w["lightgbm"] + w["xgboost"]
    if total <= 0:
        return {"catboost": 1 / 3, "lightgbm": 1 / 3, "xgboost": 1 / 3}
    return {k: v / total for k, v in w.items()}


def _build_catboost():
    return CatBoostClassifier(
        iterations=get_config("model.catboost.iterations", 500),
        depth=get_config("model.catboost.depth", 6),
        learning_rate=get_config("model.catboost.learning_rate", 0.05),
        random_seed=42,
        verbose=0,
    )


def _build_lightgbm():
    return LGBMClassifier(
        n_estimators=get_config("model.lightgbm.n_estimators", 500),
        max_depth=get_config("model.lightgbm.max_depth", 6),
        learning_rate=get_config("model.lightgbm.learning_rate", 0.05),
        random_state=42,
        verbose=-1,
        n_jobs=-1,
    )


def _build_xgboost():
    return XGBClassifier(
        n_estimators=get_config("model.xgboost.n_estimators", 500),
        max_depth=get_config("model.xgboost.max_depth", 6),
        learning_rate=get_config("model.xgboost.learning_rate", 0.05),
        random_state=42,
        use_label_encoder=False,
        eval_metric="logloss",
        n_jobs=-1,
    )


class LimitUpModel:
    """买入模型（梯度提升集成）

    CatBoost + LightGBM + XGBoost 线性加权概率平均
    预测: open(t+1) -> open(t+max_holding+1) 收益 >= label_threshold 的概率
    """

    def __init__(self):
        self.models = {}
        self.factor_cols = get_factor_columns()
        self.threshold = get_config("model.predict_threshold", 0.50)
        self.weights = _get_ensemble_weights()
        log.info(f"买入模型初始化 | 因子: {self.factor_cols} | 阈值: {self.threshold}")
        log.info(f"集成权重: {self.weights}")

    def prepare_data(self, df: pd.DataFrame) -> tuple:
        """准备训练数据

        时序对齐:
          X = t-1 日因子值
          Y = open(t+1) -> open(t+max_holding+1) 收益 >= label_threshold%
        """
        df = df.copy()
        label_threshold = get_config("model.label_threshold", 3.0)
        max_holding = get_config("trading.max_holding_days", 5)

        shift_buy = -1
        shift_sell = -(max_holding + 1)

        if "open" in df.columns:
            if "ts_code" in df.columns:
                buy_open = df.groupby("ts_code")["open"].shift(shift_buy)
                sell_open = df.groupby("ts_code")["open"].shift(shift_sell)
            else:
                buy_open = df["open"].shift(shift_buy)
                sell_open = df["open"].shift(shift_sell)
            fwd_ret = (sell_open - buy_open) / buy_open
            df["label"] = (fwd_ret >= label_threshold / 100.0).astype(int)
        else:
            if "ts_code" in df.columns:
                fwd_close = df.groupby("ts_code")["close"].shift(-1)
            else:
                fwd_close = df["close"].shift(-1)
            df["label"] = ((fwd_close - df["close"]) / df["close"] >= label_threshold / 100.0).astype(int)

        X = df[self.factor_cols]
        Y = df["label"]
        valid = X.notna().all(axis=1) & Y.notna()
        X = X[valid]
        Y = Y[valid].astype(int)

        log.info(f"买入模型训练数据: {len(X)} 条 | 正样本: {Y.sum()} 条 ({Y.mean():.1%})")
        log.info(f"标签定义: open(t+1)->open(t+{max_holding+1}) 收益 >= {label_threshold}%")
        return X, Y

    def train(self, df: pd.DataFrame) -> dict:
        """训练梯度提升集成买入模型"""
        X, Y = self.prepare_data(df)

        if len(X) < 100:
            log.warning(f"训练数据太少({len(X)}条)")

        train_ratio = get_config("model.train_ratio", 0.8)
        X_train, X_test, Y_train, Y_test = train_test_split(
            X, Y, train_size=train_ratio, shuffle=False
        )

        results = {}
        for name, builder in [("catboost", _build_catboost),
                              ("lightgbm", _build_lightgbm),
                              ("xgboost", _build_xgboost)]:
            log.info(f"训练 {name} 买入模型 ...")
            try:
                m = builder()
                m.fit(X_train, Y_train)
                prob = m.predict_proba(X_test)[:, 1]
                pred = (prob >= self.threshold).astype(int)
                acc = accuracy_score(Y_test, pred)
                auc = roc_auc_score(Y_test, prob)
                log.info(f"  {name}: acc={acc:.2%} AUC={auc:.2%}")
                results[name] = {"acc": acc, "auc": auc}
                self.models[name] = m
            except Exception as e:
                log.warning(f"  {name} 训练失败: {e}")

        if self.models:
            ensemble_prob = self._ensemble_predict_proba(X_test)
            for t in [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]:
                pred_t = (ensemble_prob >= t).astype(int)
                a_t = accuracy_score(Y_test, pred_t)
                log.info(f"  集成 threshold {t:.2f}: acc={a_t:.2%} pos={(pred_t==1).sum()}/{len(pred_t)}")

            ensemble_pred = (ensemble_prob >= self.threshold).astype(int)
            ensemble_acc = accuracy_score(Y_test, ensemble_pred)
            ensemble_auc = roc_auc_score(Y_test, ensemble_prob)
            log.info(f"集成买入模型训练完成 | acc={ensemble_acc:.2%} AUC={ensemble_auc:.2%}")

            importances = {}
            if "catboost" in self.models:
                importances = dict(zip(self.factor_cols, self.models["catboost"].feature_importances_))
                log.info(f"特征重要性(CatBoost): {importances}")
        else:
            log.error("所有模型训练失败!")
            return {"accuracy": 0}

        self.save()
        return {"accuracy": ensemble_acc, "models": results}

    def _ensemble_predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """集成预测概率"""
        probs = np.zeros(len(X))
        for name, model in self.models.items():
            prob = model.predict_proba(X)[:, 1]
            probs += self.weights.get(name, 1 / 3) * prob
        return probs

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """预测涨停概率"""
        if not self.models:
            self.load()

        for col in self.factor_cols:
            if col not in df.columns:
                df[col] = np.nan

        X = df[self.factor_cols]
        probs = np.zeros(len(df))
        valid_mask = X.notna().all(axis=1)
        if valid_mask.any() and self.models:
            probs[valid_mask.values] = self._ensemble_predict_proba(X[valid_mask])
        return probs

    def save(self, path=None):
        path = path or MODEL_PATH
        if self.models:
            joblib.dump(self.models, path)
            log.info(f"买入模型已保存: {path}")

    def load(self, path=None):
        path = path or MODEL_PATH
        if path.exists():
            self.models = joblib.load(path)
            log.info(f"买入模型已加载: {path} ({list(self.models.keys())})")
        else:
            log.warning(f"模型文件不存在: {path}")


class ExitModel:
    """卖出模型（梯度提升集成）

    预测次日上涨概率。持仓期间每日评估，如果预测次日上涨概率极低则提前卖出。
    阈值设得很低(0.35)，只在模型非常看跌时才触发。

    特征 = 买入模型因子 + days_held + current_pnl
    标签 = 次日收盘 > 当日收盘 (1=涨, 0=跌)
    """

    def __init__(self):
        self.models = {}
        self.factor_cols = get_factor_columns()
        self.exit_cols = self.factor_cols + ["days_held", "current_pnl"]
        self.threshold = get_config("model.exit_threshold", 0.35)
        self.weights = _get_ensemble_weights()
        log.info(f"卖出模型初始化 | 特征: {self.exit_cols} | 阈值: {self.threshold}")

    def prepare_data(self, df: pd.DataFrame) -> tuple:
        """构建卖出模型训练数据"""
        df = df.copy()
        max_holding = get_config("trading.max_holding_days", 5)
        factor_cols = self.factor_cols

        rows = []

        if "ts_code" in df.columns:
            groups = df.groupby("ts_code")
        else:
            groups = [(None, df)]

        for ts_code, group in groups:
            if "ts_code" in df.columns:
                group = group.sort_values("trade_date").reset_index(drop=True)

            for i in range(len(group)):
                if i + 1 >= len(group):
                    continue

                factor_vals = {}
                skip = False
                for col in factor_cols:
                    v = group.iloc[i].get(col, np.nan)
                    if pd.isna(v):
                        skip = True
                        break
                    factor_vals[col] = v
                if skip:
                    continue

                curr_close = group.iloc[i]["close"]
                next_close = group.iloc[i + 1]["close"]
                label = 1 if next_close > curr_close else 0

                for days_held in range(1, max_holding + 1):
                    if i - days_held < 0:
                        continue

                    entry_close = group.iloc[i - days_held]["close"]
                    if entry_close <= 0:
                        continue
                    current_pnl = (curr_close - entry_close) / entry_close

                    row = factor_vals.copy()
                    row["days_held"] = days_held
                    row["current_pnl"] = current_pnl
                    row["label"] = label
                    rows.append(row)

        if not rows:
            log.warning("卖出模型: 无训练数据")
            return pd.DataFrame(), pd.Series()

        result = pd.DataFrame(rows)
        X = result[self.exit_cols]
        Y = result["label"]
        valid = X.notna().all(axis=1) & Y.notna()
        X = X[valid]
        Y = Y[valid].astype(int)

        log.info(f"卖出模型训练数据: {len(X)} 条 | 正样本: {Y.sum()} 条 ({Y.mean():.1%})")
        return X, Y

    def train(self, df: pd.DataFrame) -> dict:
        """训练梯度提升集成卖出模型"""
        X, Y = self.prepare_data(df)

        if len(X) < 100:
            log.warning(f"卖出模型训练数据太少({len(X)}条)")
            return {"accuracy": 0}

        train_ratio = get_config("model.train_ratio", 0.8)
        X_train, X_test, Y_train, Y_test = train_test_split(
            X, Y, train_size=train_ratio, shuffle=False
        )

        for name, builder in [("catboost", _build_catboost),
                              ("lightgbm", _build_lightgbm),
                              ("xgboost", _build_xgboost)]:
            log.info(f"训练 {name} 卖出模型 ...")
            try:
                m = builder()
                m.fit(X_train, Y_train)
                prob = m.predict_proba(X_test)[:, 1]
                pred = (prob >= 0.5).astype(int)
                acc = accuracy_score(Y_test, pred)
                auc = roc_auc_score(Y_test, prob)
                log.info(f"  {name}: acc={acc:.2%} AUC={auc:.2%}")
                self.models[name] = m
            except Exception as e:
                log.warning(f"  {name} 训练失败: {e}")

        if self.models:
            ensemble_prob = self._ensemble_predict_proba(X_test)
            ensemble_pred = (ensemble_prob >= 0.5).astype(int)
            acc = accuracy_score(Y_test, ensemble_pred)
            auc = roc_auc_score(Y_test, ensemble_prob)
            log.info(f"集成卖出模型训练完成 | acc={acc:.2%} AUC={auc:.2%}")

            importances = {}
            if "catboost" in self.models:
                importances = dict(zip(self.exit_cols, self.models["catboost"].feature_importances_))
                log.info(f"卖出模型特征重要性(CatBoost): {importances}")
        else:
            log.error("卖出模型全部训练失败!")
            return {"accuracy": 0}

        self.save()
        return {"accuracy": acc, "feature_importances": importances}

    def _ensemble_predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """集成预测概率"""
        probs = np.zeros(len(X))
        for name, model in self.models.items():
            prob = model.predict_proba(X)[:, 1]
            probs += self.weights.get(name, 1 / 3) * prob
        return probs

    def predict_should_sell(self, factor_dict: dict, days_held: int, current_pnl: float) -> bool:
        """预测是否应该卖出

        返回 True = 建议卖出, False = 建议持有
        阈值很低(0.35)，只在模型强烈看跌时才触发
        """
        if not self.models:
            return False

        row = factor_dict.copy()
        row["days_held"] = float(days_held)
        row["current_pnl"] = float(current_pnl)

        X = pd.DataFrame([row])[self.exit_cols]

        if X.isna().any().any():
            return False

        prob_up = self._ensemble_predict_proba(X)[0]
        return prob_up < self.threshold

    def save(self, path=None):
        path = path or EXIT_MODEL_PATH
        if self.models:
            joblib.dump(self.models, path)
            log.info(f"卖出模型已保存: {path}")

    def load(self, path=None):
        path = path or EXIT_MODEL_PATH
        if path.exists():
            self.models = joblib.load(path)
            log.info(f"卖出模型已加载: {path}")
        else:
            log.warning(f"卖出模型文件不存在: {path}")
