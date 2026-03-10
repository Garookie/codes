#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FRLG共通操作ミックスイン・ユーティリティ"""

import os
from Commands.Keys import Button

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

ARASUJI_TEMPLATE = os.path.join(os.path.dirname(__file__), 'Template', 'ui', 'arasuji.png')
ARASUJI_CROP = [125, 15, 370, 70]


class FRLGBase:
    """FRLG共通操作。ImageProcPythonCommand と多重継承して使う。"""

    def _load_digit_templates(self, template_dir, binarize_mode='fixed', threshold=127):
        """
        数字テンプレート画像(0.png〜9.png)を読み込み2値化して返す。

        Args:
            template_dir: テンプレートディレクトリパス
            binarize_mode: 'fixed'=固定閾値BINARY, 'fixed_inv'=固定閾値BINARY_INV
            threshold: binarize_mode='fixed' 時の閾値
        Returns:
            dict[int, ndarray]: 数字 → 2値化画像
        """
        if not _CV2_AVAILABLE:
            return {}

        templates = {}
        if not os.path.isdir(template_dir):
            print(f'警告: 数字テンプレートディレクトリが見つかりません: {template_dir}')
            return templates

        for d in range(10):
            path = os.path.join(template_dir, f'{d}.png')
            if not os.path.exists(path):
                continue
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            if binarize_mode == 'fixed_inv':
                _, img = cv2.threshold(img, threshold, 255, cv2.THRESH_BINARY_INV)
            else:
                _, img = cv2.threshold(img, threshold, 255, cv2.THRESH_BINARY)
            templates[d] = img

        return templates

    def _read_number_from_roi(self, binary_image, digit_templates, threshold=0.8, group_distance=15):
        """
        2値化済みROI画像からテンプレートマッチングで数値を読み取る。

        Args:
            binary_image: 2値化済みROI画像(グレースケール)
            digit_templates: _load_digit_templates() の戻り値
            threshold: マッチング閾値
            group_distance: 同一桁とみなすピクセル距離
        Returns:
            int | None: 認識した数値、失敗時None
        """
        if not _CV2_AVAILABLE or not digit_templates:
            return None

        matches = []
        for digit, tmpl in digit_templates.items():
            th, tw = tmpl.shape[:2]
            if th > binary_image.shape[0] or tw > binary_image.shape[1]:
                continue
            result = cv2.matchTemplate(binary_image, tmpl, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)
            for pt_y, pt_x in zip(*locations):
                score = result[pt_y, pt_x]
                matches.append((pt_x, digit, score))

        if not matches:
            return None

        # 近接マッチをグループ化（同一桁の重複除去）
        matches.sort(key=lambda m: m[0])
        grouped = []
        for x_pos, digit, score in matches:
            merged = False
            for g in grouped:
                if abs(x_pos - g['x']) < group_distance:
                    if score > g['score']:
                        g['x'] = x_pos
                        g['digit'] = digit
                        g['score'] = score
                    merged = True
                    break
            if not merged:
                grouped.append({'x': x_pos, 'digit': digit, 'score': score})

        grouped.sort(key=lambda g: g['x'])
        number_str = ''.join(str(g['digit']) for g in grouped)

        try:
            return int(number_str)
        except ValueError:
            return None

    def reset_game(self):
        """ソフトリセット → あらすじスキップ → フィールド復帰"""
        self.press([Button.A, Button.B, Button.X, Button.Y], duration=0.5, wait=0.1)
        while not self.isContainTemplate(ARASUJI_TEMPLATE, threshold=0.8, show_value=False, crop=ARASUJI_CROP):
            self.press(Button.A, duration=0.1, wait=0.1)
        self.press(Button.B, duration=1, wait=1)

    def send_notice(self, message=None, embeds=None):
        """Discord通知ラッパー。discord_mode有効時のみ送信。"""
        if getattr(self, 'discord_mode', False):
            self.noticeDiscord(message=message, embeds=embeds)
