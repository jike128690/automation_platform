# -*- coding: utf-8 -*-
"""批量配置页（T12.2）：常规设置 + 浏览器设置表单，保存至 tb_system_config。

表单字段与 LDM 2.10 逐项对应（图3 常规设置 / 图4 浏览器设置）；
数值范围由 QSpinBox/QComboBox 原生约束 + config_service 保存校验双层保证；
代理地址格式在保存前校验（http(s)://host:port），校验失败阻断保存并提示；
proxy_password 输入框掩码回显，保存后不回显原文（计划第 8 节脱敏要求）。

【保存并应用】→ config_service.save_config（单行 upsert）→ 引擎下次运行
读取生效（T12.3 修改配置后重新运行即生效）。
"""
from __future__ import annotations

import re

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton

from app.db.services.config_service import get_config, save_config

_PROXY_RE = re.compile(r"^https?://[^\s:]+:\d{1,5}$")
RETENTION_OPTIONS = [(1, "1 天"), (3, "3 天"), (5, "5 天"), (7, "7 天"),
                     (30, "30 天"), (-1, "永久保留")]


class BatchConfigPage(QWidget):
    """批量配置页：图3 常规设置 + 图4 浏览器设置（tb_system_config 单例）。"""

    sig_back_home = pyqtSignal()  # 保存成功/返回 → 主窗口切回首页

    def __init__(self, db_engine, parent=None):
        super().__init__(parent)
        self._db_engine = db_engine
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------- UI 构建

    def _build_ui(self):
        # ---- 常规设置（图3） ----
        general = QGroupBox("常规设置", self)
        form1 = QFormLayout(general)
        self.project_name = QLineEdit(self)
        self.project_name.setMaxLength(100)
        self.report_save_path = QLineEdit(self)
        self.run_mode = QComboBox(self)
        self.run_mode.addItems(["TEST", "DEBUG"])  # TEST 按需重跑 / DEBUG 单步暂停
        self.start_delay_sec = QSpinBox(self)
        self.start_delay_sec.setRange(0, 60)
        form1.addRow("测试项目名称", self.project_name)
        form1.addRow("测试报告保存路径", self.report_save_path)
        form1.addRow("运行模式", self.run_mode)
        form1.addRow("测试启动前延迟(秒)", self.start_delay_sec)

        # ---- 浏览器设置（图4） ----
        browser = QGroupBox("浏览器设置", self)
        form2 = QFormLayout(browser)
        self.browser_type = QComboBox(self)
        self.browser_type.addItems(["CHROME", "CHROMIUM"])
        self.driver_path = QLineEdit(self)
        self.exec_timeout_sec = QSpinBox(self)
        self.exec_timeout_sec.setRange(5, 300)
        self.implicit_wait_sec = QSpinBox(self)
        self.implicit_wait_sec.setRange(0, 60)
        self.page_load_strategy = QComboBox(self)
        self.page_load_strategy.addItems(["NORMAL", "EAGER", "NONE"])
        self.env_profile = QComboBox(self)
        self.env_profile.addItems(["PROD", "STAGE", "TEST", "DEV"])
        form2.addRow("浏览器选择", self.browser_type)
        form2.addRow("默认驱动路径", self.driver_path)
        form2.addRow("测试执行超时(秒)", self.exec_timeout_sec)
        form2.addRow("元素查找等待(秒)", self.implicit_wait_sec)
        form2.addRow("页面加载策略", self.page_load_strategy)
        form2.addRow("环境配置", self.env_profile)

        # ---- 代理设置（图4） ----
        proxy = QGroupBox("代理设置", self)
        form3 = QFormLayout(proxy)
        self.proxy_mode = QComboBox(self)
        self.proxy_mode.addItems(["NO_PROXY", "SYSTEM", "CUSTOM"])
        self.proxy_address = QLineEdit(self)
        self.proxy_address.setPlaceholderText("http://ip:port")
        self.proxy_auth_enabled = QCheckBox("开启代理认证", self)
        self.proxy_username = QLineEdit(self)
        self.proxy_password = QLineEdit(self)
        self.proxy_password.setEchoMode(QLineEdit.EchoMode.Password)
        form3.addRow("代理模式", self.proxy_mode)
        form3.addRow("自定义代理地址", self.proxy_address)
        form3.addRow("", self.proxy_auth_enabled)
        form3.addRow("代理认证账号", self.proxy_username)
        form3.addRow("代理认证密码", self.proxy_password)

        # ---- 清除数据项与执行选项（图4） ----
        options = QGroupBox("清除数据项与执行选项", self)
        form4 = QFormLayout(options)
        self.clear_cache = QCheckBox("浏览器缓存", self)
        self.clear_cookies = QCheckBox("Cookies", self)
        self.clear_history = QCheckBox("历史记录", self)
        clear_row = QHBoxLayout()
        clear_row.addWidget(self.clear_cache)
        clear_row.addWidget(self.clear_cookies)
        clear_row.addWidget(self.clear_history)
        clear_row.addStretch(1)
        self.retry_count = QSpinBox(self)
        self.retry_count.setRange(0, 10)
        self.screenshot_on_fail = QCheckBox("失败时自动截图", self)
        self.record_video = QCheckBox("录制执行过程 (视频)", self)
        self.media_retention_days = QComboBox(self)
        for _value, label in RETENTION_OPTIONS:
            self.media_retention_days.addItem(label)
        self.log_level = QComboBox(self)
        self.log_level.addItems(["DEBUG", "INFO", "WARN", "ERROR"])
        form4.addRow("测试前清除数据项", clear_row)
        form4.addRow("失败重试次数", self.retry_count)
        form4.addRow("", self.screenshot_on_fail)
        form4.addRow("", self.record_video)
        form4.addRow("媒体文件保留期", self.media_retention_days)
        form4.addRow("日志级别", self.log_level)

        # ---- 滚动容器 + 底部按钮 ----
        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.addWidget(general)
        body_layout.addWidget(browser)
        body_layout.addWidget(proxy)
        body_layout.addWidget(options)
        body_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)

        self.btn_save = PrimaryPushButton("保存并应用", self)
        self.btn_back = QPushButton("返回", self)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_save)
        buttons.addWidget(self.btn_back)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)

        self.btn_save.clicked.connect(self._on_save)
        self.btn_back.clicked.connect(self.sig_back_home.emit)

    # ---------------------------------------------------------- 数据装载

    def refresh(self):
        """从 tb_system_config 装载当前配置到表单（进入页面时调用）。"""
        config = get_config(self._db_engine)
        self.project_name.setText(config.project_name)
        self.report_save_path.setText(config.report_save_path)
        self.run_mode.setCurrentText(config.run_mode)
        self.start_delay_sec.setValue(config.start_delay_sec)
        self.browser_type.setCurrentText(config.browser_type)
        self.driver_path.setText(config.driver_path or "")
        self.exec_timeout_sec.setValue(config.exec_timeout_sec)
        self.implicit_wait_sec.setValue(config.implicit_wait_sec)
        self.page_load_strategy.setCurrentText(config.page_load_strategy)
        self.env_profile.setCurrentText(config.env_profile)
        self.proxy_mode.setCurrentText(config.proxy_mode)
        self.proxy_address.setText(config.proxy_address or "")
        self.proxy_auth_enabled.setChecked(bool(config.proxy_auth_enabled))
        self.proxy_username.setText(config.proxy_username or "")
        # proxy_password 不回显原文（计划第 8 节脱敏）：保留占位标记，未改动则不覆盖
        self.proxy_password.setProperty("masked", bool(config.proxy_password))
        self.proxy_password.setPlaceholderText(
            "已设置（输入新值覆盖）" if config.proxy_password else ""
        )
        self.clear_cache.setChecked(bool(config.clear_cache))
        self.clear_cookies.setChecked(bool(config.clear_cookies))
        self.clear_history.setChecked(bool(config.clear_history))
        self.retry_count.setValue(config.retry_count)
        self.screenshot_on_fail.setChecked(bool(config.screenshot_on_fail))
        self.record_video.setChecked(bool(config.record_video))
        index = next(
            (i for i, (value, _) in enumerate(RETENTION_OPTIONS)
             if value == config.media_retention_days),
            2,  # 默认 5 天
        )
        self.media_retention_days.setCurrentIndex(index)
        self.log_level.setCurrentText(config.log_level)

    def collect_updates(self) -> dict:
        """收集表单 → 配置字段 dict（不落库）。"""
        retention = RETENTION_OPTIONS[self.media_retention_days.currentIndex()][0]
        updates = {
            "project_name": self.project_name.text().strip(),
            "report_save_path": self.report_save_path.text().strip(),
            "run_mode": self.run_mode.currentText(),
            "start_delay_sec": self.start_delay_sec.value(),
            "browser_type": self.browser_type.currentText(),
            "driver_path": self.driver_path.text().strip() or None,
            "exec_timeout_sec": self.exec_timeout_sec.value(),
            "implicit_wait_sec": self.implicit_wait_sec.value(),
            "page_load_strategy": self.page_load_strategy.currentText(),
            "proxy_mode": self.proxy_mode.currentText(),
            "proxy_address": self.proxy_address.text().strip() or None,
            "proxy_auth_enabled": int(self.proxy_auth_enabled.isChecked()),
            "proxy_username": self.proxy_username.text().strip() or None,
            "clear_cache": int(self.clear_cache.isChecked()),
            "clear_cookies": int(self.clear_cookies.isChecked()),
            "clear_history": int(self.clear_history.isChecked()),
            "env_profile": self.env_profile.currentText(),
            "retry_count": self.retry_count.value(),
            "screenshot_on_fail": int(self.screenshot_on_fail.isChecked()),
            "record_video": int(self.record_video.isChecked()),
            "media_retention_days": retention,
            "log_level": self.log_level.currentText(),
        }
        # 密码仅在输入新值时覆盖（掩码不回显原文）
        new_password = self.proxy_password.text()
        if new_password:
            updates["proxy_password"] = new_password
        return updates

    # ---------------------------------------------------------- 保存

    def validate(self, updates: dict) -> str | None:
        """保存校验（路径/代理格式）；通过返回 None，失败返回提示文案。"""
        if not updates["project_name"]:
            return "测试项目名称不能为空"
        if not updates["report_save_path"]:
            return "测试报告保存路径不能为空"
        if updates["proxy_mode"] == "CUSTOM":
            if not updates["proxy_address"]:
                return "自定义代理模式必须填写代理地址（http://ip:port）"
            if not _PROXY_RE.match(updates["proxy_address"]):
                return "代理地址格式错误，应为 http://ip:port 或 https://ip:port"
        if updates["proxy_auth_enabled"] and not updates["proxy_username"]:
            return "开启代理认证后必须填写认证账号"
        return None

    def _on_save(self):
        updates = self.collect_updates()
        error = self.validate(updates)
        if error:
            QMessageBox.warning(self, "保存失败", error)
            return
        save_config(self._db_engine, updates)
        QMessageBox.information(
            self, "保存成功",
            "配置已保存并应用（下次运行测试时生效）",
        )
        self.sig_back_home.emit()
