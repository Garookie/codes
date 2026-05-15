from Commands.Keys import Button, Direction, Stick
from Commands.PythonCommandBase import ImageProcPythonCommand
from Commands.PythonCommands.settings_manager import SettingsManager
from Commands.PythonCommands.PokemonZA.za_utils import ZAUtilsMixin
import cv2
import numpy as np
import os
import time
from datetime import timedelta

SETTING_FILE = 'LegendaryShinySetting.json'
SETTING_SECTION = 'LegendaryShiny'
TARGET_DIALOG_KEY = '対象ポケモン'
CALORIE_DIALOG_KEY = '停止カロリー（kcal以下）'
DISCORD_DIALOG_KEY = 'Discord通知'
SLEEP_ON_FINISH_DIALOG_KEY = '終了時にSwitchをスリープ'
LAP_COUNT_DIALOG_KEY = '周回数（継続用）'
TARGET_OPTIONS = {
    'latios': 'ラティオス',
    'latias': 'ラティアス',
    'virizion': 'ビリジオン',
    'cobalion': 'コバルオン',
    'terrakion': 'テラキオン',
}
TARGET_ALIASES = {
    'latios': 'latios',
    'ラティオス': 'latios',
    'latias': 'latias',
    'ラティアス': 'latias',
    'virizion': 'virizion',
    'ビリジオン': 'virizion',
    'cobalion': 'cobalion',
    'コバルオン': 'cobalion',
    'terrakion': 'terrakion',
    'テラキオン': 'terrakion',
}
CALORIE_HUNT_TARGETS = {'latias', 'virizion', 'cobalion'}
CALORIE_TARGET = 1000
CALORIE_TARGET_OPTIONS = (1000, 1500, 2000)
CALORIE_TARGET_LABELS = [str(value) for value in CALORIE_TARGET_OPTIONS]
CALORIE_MOVE_DURATIONS = {
    'latias': (4.1, 4.0),
    'virizion': (5, 5.3),
    'cobalion': (4.5, 4.5),
}
TERRAKION_MOVE_DURATION = 0.5
TERRAKION_FIELD_TIMEOUT = 30
LATIOS_SEARCH_ROI = (410, 150, 930, 330)
UNCERTAIN_LOG_INTERVAL = 30.0
POLL_INTERVAL = 0.3
NORMAL_BLUE_HSV_LOWER = np.array([92, 70, 80])
NORMAL_BLUE_HSV_UPPER = np.array([112, 255, 255])
SHINY_GREEN_HSV_LOWER = np.array([45, 70, 80])
SHINY_GREEN_HSV_UPPER = np.array([82, 255, 255])
LATIOS_COMPONENT_MIN_AREA = 80
LATIOS_COMPONENT_MAX_AREA = 8000
LATIOS_COMPONENT_MIN_WIDTH = 12
LATIOS_COMPONENT_MIN_HEIGHT = 8
LATIOS_COMPONENT_MAX_WIDTH = 180
LATIOS_COMPONENT_MAX_HEIGHT = 120
LATIOS_COMPONENT_MIN_ASPECT = 0.4
LATIOS_COMPONENT_MAX_ASPECT = 6.0
LATIOS_BBOX_PADDING = 4
NORMAL_BLUE_PIXELS_MIN = 180
NORMAL_BLUE_DOMINANCE_RATIO = 1.8
SHINY_GREEN_PIXELS_MIN = 70
SHINY_GREEN_RATIO_MIN = 0.35
NORMAL_REQUIRED_FRAMES = 2
SHINY_REQUIRED_FRAMES = 2


class LegendaryShiny(ImageProcPythonCommand, ZAUtilsMixin):
    NAME = '【ZA】準伝説色違い厳選'
    TAGS = ['ZA']

    def __init__(self, cam, gui=None):
        super().__init__(cam)
        self.gui = gui
        self.template_dir = os.path.join(os.path.dirname(__file__), 'Template')
        self.unknown_template = os.path.join(self.template_dir, 'unknown.png')
        self.settings = SettingsManager(
            setting_name=SETTING_FILE,
            path=os.path.dirname(__file__)
        )
        self._load_settings()

    def _load_settings(self):
        if not self.settings.has_section(SETTING_SECTION):
            self.settings.add_section(SETTING_SECTION)
            self.settings.set(SETTING_SECTION, 'target', 'latios')
            self.settings.set(SETTING_SECTION, 'calorie_target', CALORIE_TARGET)
            self.settings.set(SETTING_SECTION, 'enable_discord_notice', False)
            self.settings.set(SETTING_SECTION, 'sleep_on_finish', True)
            self.settings.set(SETTING_SECTION, 'lap_count', 0)
        self.target = self._normalize_target(self.settings.get(SETTING_SECTION, 'target', 'latios'))
        self.calorie_target = self._normalize_calorie_target(
            self.settings.get_int(SETTING_SECTION, 'calorie_target', CALORIE_TARGET)
        )
        self.enable_discord_notice = self.settings.get_bool(SETTING_SECTION, 'enable_discord_notice', False)
        self.sleep_on_finish = self.settings.get_bool(SETTING_SECTION, 'sleep_on_finish', True)
        self.lap_count = self.settings.get_int(SETTING_SECTION, 'lap_count', 0)

    def _normalize_target(self, value):
        target = str(value).strip() if value is not None else ''
        return TARGET_ALIASES.get(target, target)

    def _normalize_calorie_target(self, value):
        try:
            calorie_target = int(value)
        except (TypeError, ValueError):
            return CALORIE_TARGET
        if calorie_target not in CALORIE_TARGET_OPTIONS:
            return CALORIE_TARGET
        return calorie_target

    def _save_settings(self):
        self.settings.set(SETTING_SECTION, 'target', self.target)
        self.settings.set(SETTING_SECTION, 'calorie_target', self.calorie_target)
        self.settings.set(SETTING_SECTION, 'enable_discord_notice', self.enable_discord_notice)
        self.settings.set(SETTING_SECTION, 'sleep_on_finish', self.sleep_on_finish)
        self.settings.set(SETTING_SECTION, 'lap_count', self.lap_count)

    def _dialog_value(self, ret, key, index, default=None):
        if isinstance(ret, dict):
            return ret.get(key, default)
        if isinstance(ret, list) and len(ret) > index:
            return ret[index]
        return default

    def _resolve_target_from_dialog(self, ret):
        raw_target = self._dialog_value(ret, TARGET_DIALOG_KEY, 0)
        target = self._normalize_target(raw_target)
        print(f'対象選択(raw): {raw_target} -> {target}')
        if target not in TARGET_OPTIONS:
            print(f'ERROR: 対象ポケモンの設定値を解釈できません: {raw_target}')
            self.finish()
            return None
        return target

    def _resolve_calorie_target_from_dialog(self, ret):
        raw_calorie_target = self._dialog_value(ret, CALORIE_DIALOG_KEY, 1, CALORIE_TARGET)
        calorie_target = self._normalize_calorie_target(raw_calorie_target)
        print(f'停止カロリー選択(raw): {raw_calorie_target} -> {calorie_target}')
        return calorie_target

    def _set_param(self):
        target_labels = list(TARGET_OPTIONS.values())
        current_label = TARGET_OPTIONS.get(self.target, 'ラティオス')
        current_calorie_label = str(self._normalize_calorie_target(self.calorie_target))
        dialogue_list = [
            ["Combo", TARGET_DIALOG_KEY, target_labels, current_label],
            ["Combo", CALORIE_DIALOG_KEY, CALORIE_TARGET_LABELS, current_calorie_label],
            ["Next"],
            ["Check", DISCORD_DIALOG_KEY, self.enable_discord_notice],
            ["Check", SLEEP_ON_FINISH_DIALOG_KEY, self.sleep_on_finish],
            ["Entry", LAP_COUNT_DIALOG_KEY, str(self.lap_count)],
        ]
        ret = self.dialogue6widget("準伝説色違い厳選 設定", dialogue_list, need=dict)
        if type(ret) == bool and not ret:
            return False

        target = self._resolve_target_from_dialog(ret)
        if target is None:
            return False

        self.target = target
        self.calorie_target = self._resolve_calorie_target_from_dialog(ret)
        self.enable_discord_notice = self._dialog_value(ret, DISCORD_DIALOG_KEY, 2, False)
        self.sleep_on_finish = self._dialog_value(ret, SLEEP_ON_FINISH_DIALOG_KEY, 3, True)
        try:
            self.lap_count = int(self._dialog_value(ret, LAP_COUNT_DIALOG_KEY, 4, 0))
        except (TypeError, ValueError):
            print(f'ERROR: 周回数を数値として解釈できません: {self._dialog_value(ret, LAP_COUNT_DIALOG_KEY, 4)}')
            self.finish()
            return False
        return True

    def _print_settings(self):
        target_label = TARGET_OPTIONS.get(self.target, f'不明({self.target})')
        target_text = f'対象: {target_label} ({self.target})'
        print(target_text)
        self.print_t2(target_text)
        self.print_t2(f'停止カロリー: {self.calorie_target}kcal以下')
        self.print_t2(f'Discord通知: {"ON" if self.enable_discord_notice else "OFF"}')
        self.print_t2(f'終了時にSwitchをスリープ: {"ON" if self.sleep_on_finish else "OFF"}')
        self.print_t2(f'周回数: {self.lap_count}')

    def _finish_completed_run(self):
        self.open_map(template=self.unknown_template)
        if self.sleep_on_finish:
            self.sleep_switch()
        else:
            self.finish()

    def _wait_for_normal_or_candidate(self):
        start = time.time()
        last_log_time = start
        normal_streak = 0
        shiny_streak = 0

        while True:
            judgement = self._judge_current_frame()

            if judgement['state'] == 'normal':
                normal_streak += 1
                shiny_streak = 0
                if normal_streak >= NORMAL_REQUIRED_FRAMES:
                    return judgement
            elif judgement['state'] == 'shiny_candidate':
                shiny_streak += 1
                normal_streak = 0
                if shiny_streak >= SHINY_REQUIRED_FRAMES:
                    print('色違い候補色を検出。リセットせず停止します')
                    return judgement
            else:
                normal_streak = 0
                shiny_streak = 0

            now = time.time()
            if now - last_log_time >= UNCERTAIN_LOG_INTERVAL:
                self._print_judgement(judgement)
                print('通常色/色違いを確定できないため、判定を継続します')
                last_log_time = now

            self.wait(POLL_INTERVAL)

    def _judge_current_frame(self):
        frame = self.camera.readFrame()
        if frame is None:
            return {
                'state': 'unknown',
                'reason': 'フレーム取得失敗',
                'color': {},
            }

        color = self._measure_latios_colors(frame)
        state, reason = self._classify_latios_colors(color)

        return {
            'state': state,
            'reason': reason,
            'color': color,
        }

    def _classify_latios_colors(self, color):
        if color['total_pixels'] == 0:
            return 'unknown', '色判定ROIが空です'

        if not color.get('has_candidate', False):
            return 'unknown', 'ラティオス本体候補を検出できません'

        if self._is_normal_latios_color(color):
            return 'normal', '本体候補内で通常色の青系色量が優勢'

        if self._is_shiny_candidate_color(color):
            return 'shiny_candidate', '本体候補内で色違い候補の緑系色量を確認'

        if color['blue'] < NORMAL_BLUE_PIXELS_MIN and color['green'] < SHINY_GREEN_PIXELS_MIN:
            return 'unknown', '本体候補内の青/緑系色量が不足'

        if color['green_ratio'] >= SHINY_GREEN_RATIO_MIN:
            return 'unknown', '緑系色量はあるが色違い候補として確信不足'

        return 'unknown', '本体候補内の色比率が通常色/色違いの確定条件外'

    def _is_shiny_candidate_color(self, color):
        return (
            color['green'] >= SHINY_GREEN_PIXELS_MIN and
            color['green_ratio'] >= SHINY_GREEN_RATIO_MIN
        )

    def _is_normal_latios_color(self, color):
        return (
            color['blue'] >= NORMAL_BLUE_PIXELS_MIN and
            color['blue'] >= color['green'] * NORMAL_BLUE_DOMINANCE_RATIO
        )

    def _measure_latios_colors(self, frame):
        x1, y1, x2, y2 = LATIOS_SEARCH_ROI
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return {
                'blue': 0,
                'green': 0,
                'green_ratio': 0.0,
                'roi': LATIOS_SEARCH_ROI,
                'body_bbox': None,
                'component_bbox': None,
                'component_area': 0,
                'has_candidate': False,
                'total_pixels': 0,
            }

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        blue_mask = cv2.inRange(hsv, NORMAL_BLUE_HSV_LOWER, NORMAL_BLUE_HSV_UPPER)
        green_mask = cv2.inRange(hsv, SHINY_GREEN_HSV_LOWER, SHINY_GREEN_HSV_UPPER)
        blue_mask = self._cleanup_color_mask(blue_mask)
        green_mask = self._cleanup_color_mask(green_mask)
        body_mask = cv2.bitwise_or(blue_mask, green_mask)
        body_mask = self._cleanup_color_mask(body_mask)
        component = self._find_latios_body_component(body_mask)

        if component is None:
            return {
                'blue': 0,
                'green': 0,
                'green_ratio': 0.0,
                'roi': LATIOS_SEARCH_ROI,
                'body_bbox': None,
                'component_bbox': None,
                'component_area': 0,
                'has_candidate': False,
                'total_pixels': roi.shape[0] * roi.shape[1],
            }

        bx1 = max(component['x'] - LATIOS_BBOX_PADDING, 0)
        by1 = max(component['y'] - LATIOS_BBOX_PADDING, 0)
        bx2 = min(component['x'] + component['width'] + LATIOS_BBOX_PADDING, roi.shape[1])
        by2 = min(component['y'] + component['height'] + LATIOS_BBOX_PADDING, roi.shape[0])
        body_blue_mask = blue_mask[by1:by2, bx1:bx2]
        body_green_mask = green_mask[by1:by2, bx1:bx2]
        blue = int(cv2.countNonZero(body_blue_mask))
        green = int(cv2.countNonZero(body_green_mask))
        green_ratio = green / blue if blue > 0 else (float('inf') if green > 0 else 0.0)
        body_bbox = (x1 + bx1, y1 + by1, x1 + bx2, y1 + by2)
        component_bbox = (
            x1 + component['x'],
            y1 + component['y'],
            x1 + component['x'] + component['width'],
            y1 + component['y'] + component['height'],
        )

        return {
            'blue': blue,
            'green': green,
            'green_ratio': green_ratio,
            'roi': LATIOS_SEARCH_ROI,
            'body_bbox': body_bbox,
            'component_bbox': component_bbox,
            'component_area': component['area'],
            'has_candidate': True,
            'total_pixels': (by2 - by1) * (bx2 - bx1),
        }

    def _cleanup_color_mask(self, mask):
        kernel = np.ones((3, 3), np.uint8)
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)

    def _find_latios_body_component(self, mask):
        component_count, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        for label in range(1, component_count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            width = int(stats[label, cv2.CC_STAT_WIDTH])
            height = int(stats[label, cv2.CC_STAT_HEIGHT])
            if height == 0:
                continue
            aspect = width / height
            if not (
                LATIOS_COMPONENT_MIN_AREA <= area <= LATIOS_COMPONENT_MAX_AREA and
                LATIOS_COMPONENT_MIN_WIDTH <= width <= LATIOS_COMPONENT_MAX_WIDTH and
                LATIOS_COMPONENT_MIN_HEIGHT <= height <= LATIOS_COMPONENT_MAX_HEIGHT and
                LATIOS_COMPONENT_MIN_ASPECT <= aspect <= LATIOS_COMPONENT_MAX_ASPECT
            ):
                continue
            candidates.append({
                'x': int(stats[label, cv2.CC_STAT_LEFT]),
                'y': int(stats[label, cv2.CC_STAT_TOP]),
                'width': width,
                'height': height,
                'area': area,
            })

        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate['area'])

    def _print_judgement(self, judgement):
        color = judgement.get('color') or {}
        green_ratio = color.get('green_ratio', 0.0)
        print(
            f"判定: {judgement.get('state')} / {judgement.get('reason')} "
            f"/ blue={color.get('blue', 0)} green={color.get('green', 0)} "
            f"/ green/blue={green_ratio:.3f} "
            f"/ bbox={color.get('body_bbox')} "
            f"/ component_area={color.get('component_area', 0)}"
        )

    def do(self):
        if not self._set_param():
            return
        self._print_settings()
        self._save_settings()

        if self.target == 'latios':
            self._run_latios_shiny()
        elif self.target in CALORIE_HUNT_TARGETS:
            self._run_calorie_until_target()
        elif self.target == 'terrakion':
            self._run_terrakion_shiny()
        else:
            print(f'ERROR: 未対応の対象ポケモンです: {self.target}')
            self.finish()

    def _run_latios_shiny(self):
        start_time = time.time()
        try:
            while True:
                self.lap_count += 1
                self._save_settings()
                print(f'\n--- {self.lap_count}周目 ---')

                self.press(Button.A, wait=0.5)

                self.wait_for_field()
                self.press(Direction(Stick.RIGHT, 270), duration=0.15)

                judgement = self._wait_for_normal_or_candidate()
                self._print_judgement(judgement)

                if judgement['state'] == 'normal':
                    self.saveCapture()
                    print('通常色を検出 → ソフトリセット')
                    self.soft_reboot()
                else:
                    elapsed = time.time() - start_time
                    td = timedelta(seconds=int(elapsed))
                    msg = f'★色違い候補{TARGET_OPTIONS[self.target]}検出（要確認）★'
                    print(msg)
                    self.saveCapture()
                    embeds = self._build_embed(
                        msg,
                        fields=[
                            {'name': '周回数', 'value': str(self.lap_count), 'inline': True},
                            {'name': '経過時間', 'value': str(td), 'inline': True},
                            {'name': '判定理由', 'value': judgement.get('reason', '不明'), 'inline': False},
                        ],
                        color=self.COLOR_SHINY,
                    )
                    self.send_notice(embeds=embeds, is_shiny=True)
                    self.lap_count = 0
                    self._save_settings()
                    self._finish_completed_run()
                    break
        except Exception:
            elapsed = time.time() - start_time
            td = timedelta(seconds=int(elapsed))
            print(f"経過時間: {td}")
            self._save_settings()
            raise

    def _run_calorie_until_target(self):
        start_time = time.time()
        move_set_count = 0
        forward_duration, back_duration = CALORIE_MOVE_DURATIONS[self.target]
        print(
            f'カロリー厳選開始: {TARGET_OPTIONS[self.target]} ({self.target}) / '
            f'移動時間: {forward_duration}秒, {back_duration}秒'
        )
        self.reset_calorie_tracking()
        try:
            if self._is_calorie_target_reached(start_time):
                return

            while True:
                move_set_count += 1
                print(f'\n--- 移動セット {move_set_count} ---')

                self.press([Button.B, Direction(Stick.LEFT, 90)], duration=forward_duration)

                self.press([Button.B, Direction(Stick.LEFT, 270)], duration=back_duration)
                
                if self._is_calorie_target_reached(start_time):
                    return
        except Exception:
            elapsed = time.time() - start_time
            td = timedelta(seconds=int(elapsed))
            print(f"経過時間: {td}")
            self._save_settings()
            raise

    def _run_terrakion_shiny(self):
        start_time = time.time()
        loop_count = 0
        print(
            f'カロリー厳選開始: {TARGET_OPTIONS[self.target]} ({self.target}) / '
            f'上下移動: {TERRAKION_MOVE_DURATION}秒ずつ'
        )
        self.reset_calorie_tracking()
        try:
            while True:
                loop_count += 1
                print(f'\n--- テラキオン操作ループ {loop_count} ---')

                if not self.wait_for_field(timeout=TERRAKION_FIELD_TIMEOUT):
                    print('警告: 操作可能状態を検出できないためソフトリセットします')
                    self.soft_reboot()
                    continue

                if self._is_calorie_target_reached(start_time):
                    return

                self.press([Button.B, Direction(Stick.LEFT, 90)], duration=TERRAKION_MOVE_DURATION)
                self.press([Button.B, Direction(Stick.LEFT, 270)], duration=TERRAKION_MOVE_DURATION)
                self.press(Button.A, wait=0.5)

                if not self.wait_for_field(timeout=TERRAKION_FIELD_TIMEOUT):
                    print('警告: 操作可能状態を検出できないためソフトリセットします')
                    self.soft_reboot()
                    continue

                self.press(Button.A, wait=0.5)
        except Exception:
            elapsed = time.time() - start_time
            td = timedelta(seconds=int(elapsed))
            print(f"経過時間: {td}")
            self._save_settings()
            raise

    def _is_calorie_target_reached(self, start_time):
        confirmed_detail = self.confirm_calorie_target(
            self.calorie_target,
            continue_message='移動を継続します',
        )
        if confirmed_detail is None:
            return False

        self._finish_target_calorie(start_time, confirmed_detail['value'])
        return True

    def _finish_target_calorie(self, start_time, calorie):
        self.lap_count += 1
        elapsed = time.time() - start_time
        td = timedelta(seconds=int(elapsed))
        msg = f'{TARGET_OPTIONS[self.target]} 残りカロリー{calorie}kcal到達'
        print(f'{msg} → 停止します')
        embeds = self._build_embed(
            msg,
            fields=[
                {'name': '周回数', 'value': str(self.lap_count), 'inline': True},
                {'name': '経過時間', 'value': str(td), 'inline': True},
                {'name': '目標カロリー', 'value': f'{self.calorie_target}kcal以下', 'inline': True},
            ],
            color=self.COLOR_SUCCESS,
        )
        self.send_notice(embeds=embeds, is_shiny=True)
        self._save_settings()
        self._finish_completed_run()
