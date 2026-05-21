#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共通ユーティリティミックスイン"""

import os
import datetime
import cv2
import requests
from ImageProcessing import ImageProcessing, getImage
from Commands.Keys import Button


def _convert_cv2_format(crop_fmt='', crop=None):
    '''
    リストをopencv/pillow形式に対応するよう変換する。
    PythonCommandBase.convertCv2Format と同じ仕様。
    '''
    if crop is None or crop == []:
        return [], []

    try:
        # pillow形式
        if crop_fmt == 1 or crop_fmt == "1":
            res_cv2 = [crop[1], crop[3], crop[0], crop[2]]
        elif crop_fmt == 2 or crop_fmt == "2":
            res_cv2 = [crop[1], crop[1] + crop[3], crop[0], crop[0] + crop[2]]
        elif crop_fmt == 3 or crop_fmt == "3":
            res_cv2 = [crop[2], crop[3], crop[0], crop[1]]
        elif crop_fmt == 4 or crop_fmt == "4":
            res_cv2 = [crop[2], crop[2] + crop[3], crop[0], crop[0] + crop[1]]
        # opencv形式
        elif crop_fmt == 11 or crop_fmt == "11":
            res_cv2 = [crop[0], crop[2], crop[1], crop[3]]
        elif crop_fmt == 12 or crop_fmt == "12":
            res_cv2 = [crop[0], crop[0] + crop[2], crop[1], crop[1] + crop[3]]
        elif crop_fmt == 13 or crop_fmt == "13":
            res_cv2 = [crop[0], crop[1], crop[2], crop[3]]
        elif crop_fmt == 14 or crop_fmt == "14":
            res_cv2 = [crop[0], crop[0] + crop[1], crop[2], crop[2] + crop[3]]
        else:
            res_cv2 = [crop[1], crop[3], crop[0], crop[2]]
        res_pillow = [res_cv2[2], res_cv2[0], res_cv2[3], res_cv2[1]]
    except:
        res_cv2 = []
        res_pillow = []

    return res_cv2, res_pillow


class CommonMixin:
    """共通ユーティリティミックスイン"""

    # Discord通知用カラー定数
    COLOR_SHINY   = 0xFFD700  # 金 - 色違い関連
    COLOR_SUCCESS = 0x00CC00  # 緑 - 成功
    COLOR_INFO    = 0x3498DB  # 青 - 情報・状態報告
    COLOR_WARNING = 0xFF9900  # 橙 - 警告
    COLOR_ERROR   = 0xFF0000  # 赤 - エラー・停止

    def _build_embed(self, title, description=None, fields=None, color=None):
        """Discord通知用のembed辞書リストを構築する"""
        embed = {'title': title}
        if description is not None:
            embed['description'] = description
        if color is not None:
            embed['color'] = color
        if fields:
            embed['fields'] = fields
        return [embed]

    def send_notice(self, message=None, embeds=None, is_shiny=False):
        """Discord通知ラッパー。enable_discord_notice が True のときのみ送信する。"""
        if not getattr(self, 'enable_discord_notice', False):
            return
        self.noticeDiscord(message=message, embeds=embeds, is_shiny=is_shiny)

    def noticeDiscord(self, message=None, embeds=None, is_shiny=False):
        """ディスコードへの通知を送信"""
        if is_shiny:
            webhook_url = os.environ.get('DISCORD_SHINY_WEBHOOK_URL') or os.environ.get('DISCORD_WEBHOOK_URL')
        else:
            webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
        if not webhook_url:
            print('Warning: DISCORD_WEBHOOK_URL environment variable is not set')
            return
        data = {'content': message, 'embeds': embeds}
        try:
            requests.post(webhook_url, json=data, timeout=5)
        except Exception as e:
            print(f'警告: Discord通知の送信に失敗: {e}')

    def sleep_switch(self):
        self.hold(Button.HOME, 2)
        self.press(Button.A)
        self.finish()

    def capture_movie_on_switch(self):
        self.hold(Button.CAPTURE, 2)

    def saveTemplateMatchDebugCapture(self, template_path, threshold=0.7, use_gray=True,
                                      crop_fmt='', crop=None, mask_path=None, use_gpu=False,
                                      BGR_range=None, threshold_binary=None, crop_template=None,
                                      filename=None, show_value=False, line_thickness=2):
        '''
        isContainTemplate相当のテンプレートマッチングを実行し、
        一致時のみcrop枠と一致位置枠を描画した画像を保存する。
        '''
        crop = [] if crop is None else crop
        crop_template = [] if crop_template is None else crop_template

        crop_cv2, crop_pillow = _convert_cv2_format(crop_fmt=crop_fmt, crop=crop)
        crop_template_cv2, _ = _convert_cv2_format(crop_fmt=crop_fmt, crop=crop_template)

        src = self.camera.readFrame()
        if src is None:
            print('Debug capture failed: camera image is empty')
            return False

        if isinstance(template_path, ImageProcessing.image_type):
            template_image = template_path
            template_label = 'template_image'
        else:
            template_label = template_path
            template_file = self.get_filespec(template_path, mode='t') if hasattr(self, 'get_filespec') else template_path
            template_image = getImage(template_file, mode='color')
            if template_image is None:
                print(f'Debug capture failed: template image not found: {template_file}')
                return False

        if isinstance(mask_path, ImageProcessing.image_type):
            mask_image = mask_path
        elif mask_path is not None:
            mask_file = self.get_filespec(mask_path, mode='t') if hasattr(self, 'get_filespec') else mask_path
            mask_image = getImage(mask_file, mode='binary')
            if mask_image is None:
                print(f'Debug capture failed: mask image not found: {mask_file}')
                return False
        else:
            mask_image = None

        res, max_loc, width, height, max_val = ImageProcessing(use_gpu=use_gpu).isContainTemplate(
            src,
            template_image,
            mask_image=mask_image,
            threshold=threshold,
            use_gray=use_gray,
            crop=crop_cv2,
            BGR_range=BGR_range,
            threshold_binary=threshold_binary,
            crop_template=crop_template_cv2,
            show_image=False
        )

        if show_value:
            tm_mode = "NCC" if mask_image is not None else "ZNCC"
            print(f'{template_label} {tm_mode} value: {max_val}')

        if not res:
            return False

        debug_image = src.copy()
        if len(debug_image.shape) == 2:
            debug_image = cv2.cvtColor(debug_image, cv2.COLOR_GRAY2BGR)

        # OpenCVの色指定はBGR。crop枠は橙、一致位置枠は青で描画する。
        crop_color = (0, 165, 255)
        match_color = (255, 0, 0)

        if crop_pillow != []:
            crop_top_left = (int(crop_pillow[0]), int(crop_pillow[1]))
            crop_bottom_right = (int(crop_pillow[2]), int(crop_pillow[3]))
            cv2.rectangle(debug_image, crop_top_left, crop_bottom_right, crop_color, line_thickness)

        match_top_left = [int(max_loc[0]), int(max_loc[1])]
        if crop_pillow != []:
            match_top_left[0] += int(crop_pillow[0])
            match_top_left[1] += int(crop_pillow[1])
        match_bottom_right = (match_top_left[0] + int(width) + 1, match_top_left[1] + int(height) + 1)
        cv2.rectangle(debug_image, tuple(match_top_left), match_bottom_right, match_color, line_thickness)

        if filename is None or filename == "":
            dt_now = datetime.datetime.now()
            filename = 'debug_template_match_' + dt_now.strftime('%Y-%m-%d_%H-%M-%S') + '.png'
        elif os.path.splitext(filename)[1] == '':
            filename = filename + '.png'

        if hasattr(self, 'get_filespec'):
            save_path = self.get_filespec(filename, mode='c')
        elif os.path.isabs(filename):
            save_path = filename
        else:
            save_path = os.path.join('./Captures/', filename)

        capture_dir = os.path.dirname(save_path)
        if capture_dir and not os.path.exists(capture_dir):
            os.makedirs(capture_dir)

        if ImageProcessing().imwrite(save_path, debug_image):
            print('capture succeeded: ' + save_path)
            return True

        print('Capture Failed')
        return False
