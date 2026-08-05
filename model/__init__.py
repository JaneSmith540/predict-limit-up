"""
多元线性回归模型

流程:
  1. 用历史数据训练: X=因子值, Y=次日是否涨停(0/1)
  2. 预测: 输入因子值，输出涨停概率
  3. 概率 > 阈值 → 预测涨停
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib
from pathlib import Path

from utils import get_config, log
from factors import get_factor_columns

MODEL_PATH = Path(__file__).parent / "model.pkl"


class LimitUpModel:
    """涨停预测模型（多元线性回归）"""

    def __init__(self):
        self.model = None
        self.factor_cols = get_factor_columns()
        self.threshold = get_config("model.predict_threshold", 0.5)
        log.info(f"模型初始化 | 因子: {self.factor_cols} | 阈值: {self.threshold}")

    def prepare_data(self, df: pd.DataFrame) -> tuple:
        """
        准备训练数据

        X = 当日因子值
        Y = 次日是否涨停（涨幅>=9.5% 标记为1）
        """
        # 计算次日涨幅
        df = df.copy()
        df["next_close"] = df["close"].shift(-1)
        df["next_return"] = (df["next_close"] - df["close"]) / df["close"]
        # 涨停标记: 次日涨幅 >= 9.5%
        df["label"] = (df["next_return"] >= 0.095).astype(int)

        # 去掉最后一天（没有次日数据）
        df = df.dropna(subset=["next_close"])

        # 提取特征和标签
        X = df[self.factor_cols].dropna()
        Y = df.loc[X.index, "label"]

        log.info(f"训练数据: {len(X)} 条 | 涨停样本: {Y.sum()} 条 ({Y.mean():.1%})")
        return X, Y

    def train(self, df: pd.DataFrame) -> dict:
        """训练模型，返回评估指标"""
        X, Y = self.prepare_data(df)

        if len(X) < 100:
            log.warning(f"训练数据太少({len(X)}条)，建议至少1000条")
        if Y.sum() < 10:
            log.warning(f"涨停样本太少({Y.sum()}条)，模型可能学不好")

        # 划分训练集/测试集
        train_ratio = get_config("model.train_ratio", 0.8)
        X_train, X_test, Y_train, Y_test = train_test_split(
            X, Y, train_size=train_ratio, shuffle=False
        )

        # 训练多元线性回归
        self.model = LinearRegression()
        self.model.fit(X_train, Y_train)

        # 预测
        Y_pred_raw = self.model.predict(X_test)
        Y_pred = (Y_pred_raw >= self.threshold).astype(int)

        # 评估
        acc = accuracy_score(Y_test, Y_pred)
        report = classification_report(Y_test, Y_pred, output_dict=True)

        # 保存模型
        self.save()

        log.info(f"模型训练完成 | 准确率: {acc:.2%}")
        log.info(f"系数: {dict(zip(self.factor_cols, self.model.coef_))}")
        log.info(f"截距: {self.model.intercept_:.4f}")

        return {
            "accuracy": acc,
            "report": report,
            "coefficients": dict(zip(self.factor_cols, self.model.coef_)),
            "intercept": self.model.intercept_,
        }

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """
        预测涨停概率

        输入: 含因子列的 DataFrame
        输出: 涨停概率数组（0~1之间，越大约可能涨停）
        """
        if self.model is None:
            self.load()

        X = df[self.factor_cols].dropna()
        raw = self.model.predict(X)

        # 线性回归输出可能超出 0~1，用 clip 限制
        prob = np.clip(raw, 0, 1)
        return prob

    def predict_signal(self, df: pd.DataFrame) -> pd.Series:
        """预测并返回交易信号: True=预测涨停"""
        prob = self.predict(df)
        signal = pd.Series(prob >= self.threshold, index=df.index)
        return signal

    def save(self, path=None):
        """保存模型到磁盘"""
        path = path or MODEL_PATH
        if self.model is not None:
            joblib.dump(self.model, path)
            log.info(f"模型已保存: {path}")

    def load(self, path=None):
        """从磁盘加载模型"""
        path = path or MODEL_PATH
        if path.exists():
            self.model = joblib.load(path)
            log.info(f"模型已加载: {path}")
        else:
            log.warning(f"模型文件不存在: {path}，请先训练")
