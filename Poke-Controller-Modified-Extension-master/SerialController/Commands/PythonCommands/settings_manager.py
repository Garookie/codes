#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
統合設定管理クラス

- JSON形式で型を保持（bool, int, float, str, list）
- セクション+キーの2階層構造
- 名前付きプリセット機能
- 既存INIファイルからの自動マイグレーション
"""

from __future__ import annotations

import configparser
import glob
import json
import logging
import os

__all__ = ['SettingsManager']


class SettingsManager:

    def __init__(self, setting_name: str, path: str = os.path.dirname(__file__)):
        self._data: dict = {}
        self._path = path
        self._logger = logging.getLogger(__name__)
        self._logger.addHandler(logging.NullHandler())
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = True

        # パス解決 + INIマイグレーション
        base, ext = os.path.splitext(setting_name)
        if ext.lower() == '.ini':
            json_name = base + '.json'
            self._setting_path = os.path.join(path, json_name)
            ini_path = os.path.join(path, setting_name)
            if not os.path.exists(self._setting_path) and os.path.exists(ini_path):
                self.migrate_from_ini(ini_path)
                self.save()
                self._log(f'{setting_name} から {json_name} へマイグレーション完了')
        else:
            self._setting_path = os.path.join(path, setting_name)

        # 読み込み or 新規作成
        if os.path.exists(self._setting_path):
            self.load()
        else:
            self._data = {}
            self.save()
            self._log(f'{os.path.basename(self._setting_path)} を新規作成しました')

    def _log(self, message: str):
        try:
            self._logger.debug(message)
        except Exception:
            pass

    # ===== ファイル操作 =====

    def load(self) -> dict:
        try:
            with open(self._setting_path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
        except FileNotFoundError:
            self._log(f'{self._setting_path} not found, starting empty')
            self._data = {}
        except json.JSONDecodeError as e:
            self._log(f'{self._setting_path} JSON parse error: {e}, starting empty')
            self._data = {}
        return self._data

    def save(self):
        with open(self._setting_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, indent=4, ensure_ascii=False)
        self._log(f'{self._setting_path} save')

    def clear(self):
        self._data = {}
        self.save()

    def generate(self):
        self.clear()

    # ===== セクション操作 =====

    def add_section(self, section_name: str):
        if section_name in self._data:
            self._log(f'セクション "{section_name}" は既に存在します')
            return
        self._data[section_name] = {}
        self._log(f'セクション "{section_name}" を追加')

    def delete_section(self, section: str):
        if section in self._data:
            del self._data[section]
            self._log(f'セクション "{section}" を削除')

    def reset_sections(self):
        self._data = {}

    def has_section(self, section: str) -> bool:
        return section in self._data

    def sections(self) -> list:
        return list(self._data.keys())

    # ===== パラメータ操作 =====

    def set(self, section: str, key: str, value):
        if section not in self._data:
            self._data[section] = {}
        self._data[section][key] = value
        self.save()

    def get(self, section: str, key: str, default=None):
        try:
            return self._data[section][key]
        except KeyError:
            return default

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        val = self.get(section, key, default)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def get_float(self, section: str, key: str, default: float = 0.0) -> float:
        val = self.get(section, key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        val = self.get(section, key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() == 'true'
        return bool(val)

    # ===== プリセット機能 =====

    def _preset_dir(self) -> str:
        return os.path.join(self._path, 'preset')

    def list_presets(self) -> list:
        preset_dir = self._preset_dir()
        if not os.path.isdir(preset_dir):
            return []
        files = glob.glob(os.path.join(preset_dir, '**', '*.json'), recursive=True)
        prefix_len = len(preset_dir) + 1
        return [
            f[prefix_len:-5]
            for f in files
            if not os.path.basename(f).startswith('_')
        ]

    def load_preset(self, name: str, section: str = None) -> dict | None:
        preset_file = os.path.join(self._preset_dir(), f'{name}.json')
        try:
            with open(preset_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

        if section is not None and isinstance(data, dict):
            if section not in self._data:
                self._data[section] = {}
            self._data[section].update(data)
            self.save()

        return data

    def save_preset(self, name: str, data: dict = None, section: str = None):
        preset_dir = self._preset_dir()
        os.makedirs(preset_dir, exist_ok=True)

        if data is None and section is not None:
            data = self._data.get(section, {})
        if data is None:
            data = {}

        preset_file = os.path.join(preset_dir, f'{name}.json')
        os.makedirs(os.path.dirname(preset_file), exist_ok=True)
        with open(preset_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def save_last(self, data: dict = None, section: str = None):
        self.save_preset('_last', data=data, section=section)

    def load_last(self, section: str = None) -> dict | None:
        return self.load_preset('_last', section=section)

    # ===== INIマイグレーション =====

    def migrate_from_ini(self, ini_path: str) -> bool:
        if not os.path.exists(ini_path):
            return False

        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(ini_path, encoding='utf-8')

        self._data = {}
        for section in config.sections():
            self._data[section] = {}
            for key, value in config.items(section):
                self._data[section][key] = self._infer_type(value)

        return True

    @staticmethod
    def _infer_type(value: str):
        if value.lower() == 'true':
            return True
        if value.lower() == 'false':
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value
