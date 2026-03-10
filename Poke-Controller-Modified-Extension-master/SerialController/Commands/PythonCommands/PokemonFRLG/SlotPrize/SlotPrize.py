#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FRLG スロット景品ポケモン 個体値厳選（フルオート）

前提条件:
- NSO GBA アプリでFRLGをプレイ中
- ゲームコーナー景品交換所のNPCの前でセーブ済み
- 交換に必要なコインを所持
- 手持ちに空きがある

ステータス読み取り:
  テンプレートマッチングで数字を認識する。
  Template/number/ に 0〜9 の数字テンプレート画像が必要。

性格読み取り:
  テンプレートマッチングで性格名を認識する。
  Template/nature/ に性格名テンプレート画像を配置（自動収集あり）。
  テンプレート未登録の場合は全25種の性格を総当たりしてIVを逆算する。
"""
from Commands.PythonCommandBase import ImageProcPythonCommand
from Commands.PythonCommands.PokemonFRLG.frlg_base import FRLGBase
from Commands.PythonCommands.settings_manager import SettingsManager
from Commands.Keys import Button, Hat
import time
import os
import math
from datetime import datetime, timezone
import numpy as np
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False



# ===== 景品ポケモンデータ (Gen3 種族値) =====
PRIZE_POKEMON = {
    'ケーシィ': {
        'FR': {'coins': 180, 'level': 9},
        'LG': {'coins': 120, 'level': 9},
        'base': {'H': 25, 'A': 20, 'B': 15, 'C': 105, 'D': 55, 'S': 90},
    },
    'ピッピ': {
        'FR': {'coins': 500, 'level': 8},
        'LG': {'coins': 750, 'level': 8},
        'base': {'H': 70, 'A': 45, 'B': 48, 'C': 60, 'D': 65, 'S': 35},
    },
    'ストライク': {
        'FR': {'coins': 5500, 'level': 25},
        'LG': None,
        'base': {'H': 70, 'A': 110, 'B': 80, 'C': 55, 'D': 80, 'S': 105},
    },
    'カイロス': {
        'FR': None,
        'LG': {'coins': 2500, 'level': 18},
        'base': {'H': 65, 'A': 125, 'B': 100, 'C': 55, 'D': 70, 'S': 85},
    },
    'ミニリュウ': {
        'FR': {'coins': 2800, 'level': 18},
        'LG': {'coins': 4600, 'level': 24},
        'base': {'H': 41, 'A': 64, 'B': 45, 'C': 50, 'D': 50, 'S': 50},
    },
    'ポリゴン': {
        'FR': {'coins': 9999, 'level': 26},
        'LG': {'coins': 6500, 'level': 18},
        'base': {'H': 65, 'A': 60, 'B': 70, 'C': 85, 'D': 75, 'S': 40},
    },
}

# 性格補正テーブル
NATURES = {
    'がんばりや': None, 'さみしがり': ('A', 'B'), 'いじっぱり': ('A', 'C'),
    'やんちゃ': ('A', 'D'), 'ゆうかん': ('A', 'S'),
    'ずぶとい': ('B', 'A'), 'すなお': None, 'わんぱく': ('B', 'C'),
    'のうてんき': ('B', 'D'), 'のんき': ('B', 'S'),
    'ひかえめ': ('C', 'A'), 'おっとり': ('C', 'B'), 'てれや': None,
    'うっかりや': ('C', 'D'), 'れいせい': ('C', 'S'),
    'おだやか': ('D', 'A'), 'おとなしい': ('D', 'B'), 'しんちょう': ('D', 'C'),
    'きまぐれ': None, 'なまいき': ('D', 'S'),
    'おくびょう': ('S', 'A'), 'せっかち': ('S', 'B'), 'ようき': ('S', 'C'),
    'むじゃき': ('S', 'D'), 'まじめ': None,
}

# 景品メニュー順序（コイン枚数昇順、バージョン別）
FR_MENU_ORDER = ['ケーシィ', 'ピッピ', 'ミニリュウ', 'ストライク', 'ポリゴン']
LG_MENU_ORDER = ['ケーシィ', 'ピッピ', 'カイロス', 'ミニリュウ', 'ポリゴン']

# ===== 画面座標 (1280x720) =====
# ※実機テストで微調整が必要な場合があります

# 性格名の表示領域（つよさ画面1ページ目）
NATURE_REGION = (185, 525, 540, 575)  # 性格名表示領域（つよさ画面1ページ目）

# HP数値の表示領域（つよさ画面2ページ目、"68/68" の "/" 前の数値）
HP_REGION = (1065, 90, 1150, 140)

# ステータス数値の表示領域（つよさ画面2ページ目）
STAT_REGIONS = {
    'A': (1065, 170, 1150, 220),   # こうげき
    'B': (1065, 225, 1150, 275),   # ぼうぎょ
    'C': (1065, 285, 1150, 335),   # とくこう
    'D': (1065, 340, 1150, 390),   # とくぼう
    'S': (1065, 395, 1150, 450),   # すばやさ
}

# テンプレートマッチング設定
MATCH_THRESHOLD = 0.80  # マッチング閾値
BINARIZE_THRESHOLD = 120  # 2値化閾値
SAVE_UNMATCHED_NATURE = False  # 未マッチ性格画像を保存（デバッグ用）

# 景品リスト画面検出用クロップ領域 [x1, y1, x2, y2]
PRIZE_LIST_CROP = [205, 530, 740, 590]

# 色違い検出領域 [x1, y1, x2, y2]（つよさ画面スプライト右上、星マークの有無）
SHINY_CHECK_CROP = [550, 145, 600, 195]

# 設定ファイル
SETTING_FILE = 'SlotPrizeSetting.json'
SETTING_SECTION = 'SLOT_PRIZE'


class SlotPrize(FRLGBase, ImageProcPythonCommand):
    NAME = '【FRLG】景品ポケモン個体値厳選'
    TAGS = ['FRLG']

    def __init__(self, cam, gui=None):
        super().__init__(cam)
        self.gui = gui
        self.template_path_base = os.path.join(os.path.dirname(__file__), 'Template')
        self.number_template_path = os.path.join(self.template_path_base, 'number')
        self.digit_templates = {}  # {digit: binary_image}
        self.nature_templates = {}  # {nature_name: binary_image}
        self._nature_roi_gray = None  # 自動テンプレート保存用
        self.prize_list_template = os.path.join(self.template_path_base, 'prize_list.png')
        self.not_shiny_template = os.path.join(self.template_path_base, 'not_shiny.png')
        self.is_shiny = False
        self.detected_nature = None
        self.result_ivs = None

        # 設定ファイル読み込み
        self.settings = SettingsManager(
            setting_name=SETTING_FILE,
            path=os.path.dirname(__file__)
        )
        self._load_settings()

    def _load_settings(self):
        """設定ファイルからデフォルト値を読み込む"""
        if not self.settings.has_section(SETTING_SECTION):
            self.settings.add_section(SETTING_SECTION)
            defaults = {
                'version': 'FR（ファイアレッド）',
                'pokemon_name': 'ケーシィ',
                'target_nature': '指定なし',
                'party_position': 6,
                'iv_H': -1, 'iv_A': -1, 'iv_B': -1, 'iv_C': -1, 'iv_D': -1, 'iv_S': -1,
                'shiny_check': False,
                'discord_mode': False,
            }
            for key, value in defaults.items():
                self.settings.set(SETTING_SECTION, key, value)

        self._version_str = self.settings.get(SETTING_SECTION, 'version', 'FR（ファイアレッド）')
        self.pokemon_name = self.settings.get(SETTING_SECTION, 'pokemon_name', 'ケーシィ')
        self.target_nature = self.settings.get(SETTING_SECTION, 'target_nature', '指定なし')
        self.party_position = self.settings.get_int(SETTING_SECTION, 'party_position', 6)
        self.iv_thresholds = {
            'H': self.settings.get_int(SETTING_SECTION, 'iv_H', -1),
            'A': self.settings.get_int(SETTING_SECTION, 'iv_A', -1),
            'B': self.settings.get_int(SETTING_SECTION, 'iv_B', -1),
            'C': self.settings.get_int(SETTING_SECTION, 'iv_C', -1),
            'D': self.settings.get_int(SETTING_SECTION, 'iv_D', -1),
            'S': self.settings.get_int(SETTING_SECTION, 'iv_S', -1),
        }
        self.shiny_check = self.settings.get_bool(SETTING_SECTION, 'shiny_check', False)
        self.discord_mode = self.settings.get_bool(SETTING_SECTION, 'discord_mode', False)

    def _save_settings(self):
        """現在の設定を設定ファイルに保存"""
        updates = {
            'version': self._version_str,
            'pokemon_name': self.pokemon_name,
            'target_nature': self.target_nature,
            'party_position': self.party_position,
            'iv_H': self.iv_thresholds['H'],
            'iv_A': self.iv_thresholds['A'],
            'iv_B': self.iv_thresholds['B'],
            'iv_C': self.iv_thresholds['C'],
            'iv_D': self.iv_thresholds['D'],
            'iv_S': self.iv_thresholds['S'],
            'shiny_check': self.shiny_check,
            'discord_mode': self.discord_mode,
        }
        for key, value in updates.items():
            self.settings.set(SETTING_SECTION, key, value)

    def load_digit_templates(self):
        """Template/number/ から数字テンプレート画像を読み込む"""
        self.digit_templates = self._load_digit_templates(
            self.number_template_path, binarize_mode='fixed_inv', threshold=BINARIZE_THRESHOLD
        )
        print(f'数字テンプレート: {len(self.digit_templates)}個読み込み')

    def load_nature_templates(self):
        """Template/nature/ から性格名テンプレート画像を読み込む"""
        self.nature_template_path = os.path.join(self.template_path_base, 'nature')
        os.makedirs(self.nature_template_path, exist_ok=True)
        self.nature_templates = {}
        for name in NATURES:
            path = os.path.join(self.nature_template_path, f'{name}.png')
            if os.path.exists(path):
                buf = np.fromfile(path, dtype=np.uint8)
                img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
                _, binary = cv2.threshold(img, BINARIZE_THRESHOLD, 255, cv2.THRESH_BINARY_INV)
                self.nature_templates[name] = binary
        print(f'性格テンプレート: {len(self.nature_templates)}個読み込み')

    def set_param(self):
        """GUIダイアログで設定"""
        pokemon_names = list(PRIZE_POKEMON.keys())
        version_options = ["FR（ファイアレッド）", "LG（リーフグリーン）"]
        nature_options = ["指定なし"] + list(NATURES.keys())

        def iv_entry(stat):
            val = self.iv_thresholds[stat]
            return str(val) if val >= 0 else ''

        dialogue_list = [
            ["Combo", "バージョン", version_options, self._version_str],
            ["Combo", "景品ポケモン", pokemon_names, self.pokemon_name],
            ["Entry", "手持ちの空き位置（上から何番目, 1始まり）", str(self.party_position)],
            ["Next"],
            ["Combo", "目標性格", nature_options, self.target_nature],
            ["Entry", "H（HP）最低IV（0-31, 空欄=不問）", iv_entry('H')],
            ["Entry", "A（こうげき）最低IV（0-31, 空欄=不問）", iv_entry('A')],
            ["Entry", "B（ぼうぎょ）最低IV（0-31, 空欄=不問）", iv_entry('B')],
            ["Entry", "C（とくこう）最低IV（0-31, 空欄=不問）", iv_entry('C')],
            ["Entry", "D（とくぼう）最低IV（0-31, 空欄=不問）", iv_entry('D')],
            ["Entry", "S（すばやさ）最低IV（0-31, 空欄=不問）", iv_entry('S')],
            ["Next"],
            ["Check", "色違い検出", self.shiny_check],
            ["Check", "Discord通知", self.discord_mode],
        ]

        ret = self.dialogue6widget("景品ポケモン厳選 設定", dialogue_list)
        if type(ret) == bool and not ret:
            print("キャンセルされました")
            self.finish()

        # 設定値の取得
        def parse_iv(val_str):
            val_str = val_str.strip()
            if val_str == '':
                return -1
            try:
                v = int(val_str)
                return max(0, min(31, v))
            except ValueError:
                return -1

        self._version_str = ret[0]
        self.version = 'FR' if 'FR' in ret[0] else 'LG'
        self.pokemon_name = ret[1]
        self.party_position = int(ret[2])
        self.target_nature = ret[3]
        self.iv_thresholds = {
            'H': parse_iv(ret[4]),
            'A': parse_iv(ret[5]),
            'B': parse_iv(ret[6]),
            'C': parse_iv(ret[7]),
            'D': parse_iv(ret[8]),
            'S': parse_iv(ret[9]),
        }
        self.shiny_check = ret[10]
        self.discord_mode = ret[11]

        # メニュー位置を自動計算
        order = FR_MENU_ORDER if self.version == 'FR' else LG_MENU_ORDER
        self.menu_position = order.index(self.pokemon_name) + 1

        self._save_settings()

        # ポケモンデータ検証
        poke_data = PRIZE_POKEMON[self.pokemon_name]
        version_data = poke_data.get(self.version)
        if version_data is None:
            print(f'エラー: {self.pokemon_name}は{self.version}では入手できません')
            self.finish()
            return

        self.level = version_data['level']
        self.base_stats = poke_data['base']

        # IV条件の表示文字列
        def iv_cond(s, t):
            return f'{s}=0' if t == 0 else f'{s}>={t}'
        iv_desc = ', '.join(
            iv_cond(s, t) for s, t in self.iv_thresholds.items() if t >= 0
        ) or '全不問'

        print("------------------------------------")
        print("設定内容:")
        print(f"  バージョン: {self.version}")
        print(f"  対象: {self.pokemon_name} (Lv.{self.level})")
        print(f"  目標性格: {self.target_nature}")
        print(f"  メニュー位置: {self.menu_position}")
        print(f"  手持ち位置: {self.party_position}")
        print(f"  IV条件: {iv_desc}")
        print(f"  色違い検出: {'ON' if self.shiny_check else 'OFF'}")
        print(f"  Discord通知: {'ON' if self.discord_mode else 'OFF'}")
        print("------------------------------------")

    def do(self):
        """メインエントリーポイント"""
        self.set_param()

        # 条件チェック: 性格・IV・色違いのいずれも未指定なら終了
        has_nature = self.target_nature != '指定なし'
        has_iv = any(v >= 0 for v in self.iv_thresholds.values())
        if not has_nature and not has_iv and not self.shiny_check:
            print('エラー: 厳選条件が1つも設定されていません')
            print('  性格・IV・色違い検出のいずれかを指定してください')
            self.finish()
            return
        shiny_only = self.shiny_check and not has_nature and not has_iv

        if not CV2_AVAILABLE:
            print('エラー: OpenCV (cv2) が利用できません')
            self.finish()
            return

        # テンプレート読み込み
        self.load_digit_templates()
        if not self.digit_templates:
            print('エラー: 数字テンプレートが1つもありません')
            print(f'  {self.number_template_path} に 0.png〜9.png を配置してください')
            self.finish()
            return
        self.load_nature_templates()

        # 色違いテンプレートチェック
        if self.shiny_check and not os.path.exists(self.not_shiny_template):
            print('注意: not_shiny.png 未配置 → 色違い検出は無効')

        lap = 0
        nature_skip = 0
        program_start = time.time()
        print('\n--- 景品ポケモン厳選 開始 ---')

        while True:
            lap += 1
            lap_start = time.time()
            print(f'\n=== {lap}周目 ===')

            # 1. ポケモンを受け取る
            self.receive_pokemon()

            if shiny_only:
                # 色違いのみモード: 1ページ目だけチェック
                self.open_stats_page1()
                if self.is_shiny:
                    self._finish_selection('色違い個体を発見しました！', lap, nature_skip, program_start)
                    embeds = self._build_notice_embeds('【FRLG厳選】色違い発見！', lap, nature_skip, program_start)
                    self.send_notice(embeds=embeds)
                    self.sleep_switch()
                    return
            else:
                # 通常モード: 性格チェック + IV判定
                nature_ok = self.open_stats_screen()

                if nature_ok:
                    passed = self.check_ivs()

                    # 色違い検出: IV条件に関わらず停止
                    if self.is_shiny:
                        self._finish_selection('色違い個体を発見しました！', lap, nature_skip, program_start)
                        embeds = self._build_notice_embeds('【FRLG厳選】色違い発見！', lap, nature_skip, program_start)
                        self.send_notice(embeds=embeds)
                        self.sleep_switch()
                        return

                    if passed:
                        self._finish_selection('条件を満たす個体が見つかりました！', lap, nature_skip, program_start)
                        embeds = self._build_notice_embeds('【FRLG厳選】条件達成！', lap, nature_skip, program_start)
                        self.send_notice(embeds=embeds)
                        self.sleep_switch()
                        return
                else:
                    nature_skip += 1

            # 4. リセット → フィールド復帰
            self.reset_game()

            lap_time = time.time() - lap_start
            print(f'周回時間: {lap_time:.1f}秒')

    def _finish_selection(self, message, lap, nature_skip, program_start):
        """厳選成功時の共通処理（結果表示 + キャプチャ保存）"""
        total_time = time.time() - program_start
        print(f'\n★★★ {message} ★★★')
        print(f'周回数: {lap}（性格スキップ: {nature_skip}回）')
        print(f'所要時間: {int(total_time // 60)}分{int(total_time % 60)}秒')
        self.saveCapture()

    # ===== フェーズ別処理 =====

    def receive_pokemon(self):
        """NPCに話しかけて景品ポケモンを受け取る"""
        # A連打で景品リスト表示まで進める
        while not self.isContainTemplate(self.prize_list_template, threshold=0.8, crop=PRIZE_LIST_CROP):
            self.press(Button.A, duration=0.1, wait=0.3)

        # 景品リストで対象ポケモンを選択（↓ × menu_position-1, A）
        if self.menu_position > 1:
            self.pressRep(Hat.BTM, repeat=self.menu_position - 1, duration=0.1, interval=0.3, wait=0.2)
        self.press(Button.A, duration=0.1, wait=1.0)

        # 確認（A）
        self.press(Button.A, duration=0.1, wait=2)

        # ニックネーム「いいえ」（↓, A）
        self.press(Button.B, duration=0.1, wait=1.0)

        print('ポケモンを受け取りました')

    def check_shiny(self):
        """色違い判定: not_shiny.png にマッチしなければ色違い"""
        if not self.shiny_check:
            return False
        if not os.path.exists(self.not_shiny_template):
            return False
        matched = self.isContainTemplate(
            self.not_shiny_template, threshold=0.8,
            use_gray=True, crop=SHINY_CHECK_CROP,
        )
        return not matched

    def _open_pokemon_summary(self):
        """メニューからポケモンのつよさ画面1ページ目を開く（共通処理）"""
        # メニューを開く（X）
        self.press(Button.X, duration=0.1, wait=0.3)

        # 「ポケモン」を選択（↓, A）
        self.press(Hat.BTM, duration=0.1, wait=0.1)
        self.press(Button.A, duration=0.1, wait=1.5)

        # 手持ちの対象ポケモンを選択
        if self.party_position <= 4:
            if self.party_position > 1:
                self.pressRep(Hat.BTM, repeat=self.party_position - 1, duration=0.1, interval=0.3, wait=0.1)
        else:
            # 5-6番目は↑で回り込み（Cancel経由）が速い
            self.pressRep(Hat.TOP, repeat=8 - self.party_position, duration=0.1, interval=0.3, wait=0.1)

        # 「つよさをみる」を選択（A × 2）
        self.pressRep(Button.A, repeat=2, duration=0.1, interval=0.8, wait=0.5)
        self.wait(1)

    def open_stats_page1(self):
        """色違いのみモード: 1ページ目で色違いチェックだけ行う"""
        self._open_pokemon_summary()
        self.is_shiny = self.check_shiny()
        if self.is_shiny:
            print('★★★ 色違いを検出しました！ ★★★')
        else:
            print('色違い: なし')

    def open_stats_screen(self):
        """パーティからステータス画面を開き、性格を読み取る。

        Returns:
            True: ページ2に遷移済み（IV判定へ進む）
            False: 性格不一致（即リセットへ）
        """
        self._open_pokemon_summary()
        self.detected_nature = self.read_nature()

        # 色違いチェック
        self.is_shiny = self.check_shiny()
        if self.is_shiny:
            print('★★★ 色違いを検出しました！ ★★★')
        elif self.shiny_check:
            print('色違い: なし')

        # 目標性格チェック（色違いなら性格不問で通過）
        if not self.is_shiny:
            if self.target_nature != '指定なし' and self.detected_nature is not None:
                if self.detected_nature != self.target_nature:
                    print(f'性格不一致: {self.detected_nature}（目標: {self.target_nature}）→ スキップ')
                    return False
                else:
                    print(f'性格一致: {self.detected_nature}')

        # 2ページ目: ステータスページに移動（→）
        self.press(Hat.RIGHT, duration=0.3, wait=0.5)

        print('ステータス画面を表示しました')
        return True

    def _iv_check_failed(self, actual_iv, threshold):
        """IV判定: 0は完全一致(==0)、1以上は最低値(>=)"""
        if threshold < 0:
            return False  # 指定なし
        if threshold == 0:
            return actual_iv != 0  # 完全一致
        return actual_iv < threshold  # 最低値

    def _build_notice_embeds(self, title, lap, nature_skip, program_start):
        """Discord通知用のembeds辞書を生成"""
        total_time = time.time() - program_start
        minutes = int(total_time // 60)
        seconds = int(total_time % 60)

        # 色違い=金色、条件達成=緑
        color = 0xFFD700 if self.is_shiny else 0x00C853

        fields = [
            {'name': 'ポケモン', 'value': self.pokemon_name, 'inline': True},
            {'name': '周回数', 'value': f'{lap}回', 'inline': True},
            {'name': '所要時間', 'value': f'{minutes}分{seconds}秒', 'inline': True},
        ]
        if self.detected_nature:
            fields.append({'name': '性格', 'value': self.detected_nature, 'inline': True})
        if self.result_ivs:
            iv_str = ' / '.join(f'{k}:{v}' for k, v in self.result_ivs.items())
            fields.append({'name': '個体値', 'value': iv_str, 'inline': False})
        if self.is_shiny:
            fields.append({'name': '色違い', 'value': '★', 'inline': True})

        # 厳選条件の表示
        def iv_cond(s, t):
            return f'{s}=0' if t == 0 else f'{s}>={t}'
        iv_desc = ', '.join(
            iv_cond(s, t) for s, t in self.iv_thresholds.items() if t >= 0
        ) or '不問'
        nature_str = self.target_nature if self.target_nature != '指定なし' else '不問'
        desc = f'性格: {nature_str} / IV: {iv_desc}'

        return [{
            'title': title,
            'description': desc,
            'color': color,
            'fields': fields,
            'footer': {'text': f'性格スキップ: {nature_skip}回'},
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        }]

    def check_ivs(self):
        """テンプレートマッチングでステータスを読み取り、IVを判定する"""
        self.result_ivs = None
        img = self.camera.readFrame()

        # --- HP読み取り（性格非依存で先に判定） ---
        hp_iv = None
        hp_value = self.read_hp_number(img)
        if hp_value is not None:
            hp_iv = self.calc_hp_iv(hp_value)
            print(f'HP: {hp_value} → IV={hp_iv}')
            if self._iv_check_failed(hp_iv, self.iv_thresholds['H']):
                print(f'基準未達: H={hp_iv}（目標: {"=0" if self.iv_thresholds["H"] == 0 else ">=" + str(self.iv_thresholds["H"])}）')
                return False
        elif self.iv_thresholds['H'] >= 0:
            print('  HP: 読み取り失敗')
            return False

        # --- A-S ステータス値を読み取り ---
        stats = {}
        for stat_name, region in STAT_REGIONS.items():
            value = self.read_stat_number(img, region)
            if value is None:
                print(f'  {stat_name}: 読み取り失敗')
                return False
            stats[stat_name] = value

        print(f'ステータス: {stats}')

        nature_name = None
        ivs = None

        # 性格が検出済みの場合: その性格でIV計算を試行
        if self.detected_nature is not None:
            nature_mod = NATURES.get(self.detected_nature)
            ivs = self.calc_ivs_for_nature(stats, nature_mod)
            if ivs is not None:
                nature_name = self.detected_nature
                print(f'性格: {nature_name} → IV: {ivs}')
            else:
                print(f'性格 {self.detected_nature} でのIV計算失敗 → ブルートフォースへ')

        # 性格未検出 or IV計算失敗: ブルートフォースで性格特定
        if ivs is None:
            ivs, nature_name = self.calc_best_ivs_bruteforce(stats)
            if ivs is None:
                print('IV計算失敗（全性格で矛盾）')
                return False
            print(f'性格(推定): {nature_name} → IV: {ivs}')
            # テンプレート自動保存
            if nature_name not in self.nature_templates:
                self._save_nature_template(nature_name)
            # 目標性格チェック
            if self.target_nature != '指定なし' and nature_name != self.target_nature:
                print(f'性格不一致: {nature_name}（目標: {self.target_nature}）→ スキップ')
                return False

        # 個別ステータス判定（HP含む）
        all_ivs = {}
        if hp_iv is not None:
            all_ivs['H'] = hp_iv
        all_ivs.update(ivs)
        self.result_ivs = all_ivs

        failed = {k: v for k, v in all_ivs.items()
                  if self._iv_check_failed(v, self.iv_thresholds.get(k, -1))}
        if failed:
            print(f'基準未達: {failed}')
            return False

        return True

    def calc_best_ivs_bruteforce(self, stats):
        """全25種の性格でIVを計算し、最小IVが最大のものを返す"""
        best_ivs = None
        best_nature = None
        best_min_iv = -1

        for nature_name, nature_mod in NATURES.items():
            ivs = self.calc_ivs_for_nature(stats, nature_mod)
            if ivs is None:
                continue
            min_iv = min(ivs.values())
            if min_iv > best_min_iv:
                best_min_iv = min_iv
                best_ivs = ivs
                best_nature = nature_name

        return best_ivs, best_nature

    def calc_ivs_for_nature(self, stats, nature_mod):
        """
        特定の性格補正でIVを逆算する（HP除く）。
        nature_mod: ('上昇stat', '下降stat') or None（無補正）
        """
        ivs = {}
        level = self.level

        for stat_name in ['A', 'B', 'C', 'D', 'S']:
            if stat_name not in stats:
                continue
            base = self.base_stats[stat_name]
            actual = stats[stat_name]

            # floor((floor((2*Base + IV) * Lv / 100) + 5) * NatureMod)
            mod = 1.0
            if nature_mod is not None:
                if nature_mod[0] == stat_name:
                    mod = 1.1
                elif nature_mod[1] == stat_name:
                    mod = 0.9

            found = False
            for iv in range(31, -1, -1):
                calc = math.floor(
                    (math.floor((2 * base + iv) * level / 100) + 5) * mod
                )
                if calc == actual:
                    ivs[stat_name] = iv
                    found = True
                    break
            if not found:
                return None

        return ivs

    def calc_hp_iv(self, hp_stat):
        """HP実数値からHP IVを逆算する（Gen3、性格非依存）。
        式: floor((2*Base + IV) * Lv / 100) + Lv + 10
        """
        level = self.level
        base = self.base_stats['H']
        for iv in range(31, -1, -1):
            calc = math.floor((2 * base + iv) * level / 100) + level + 10
            if calc == hp_stat:
                return iv
        return None

    # ===== 画像処理ユーティリティ =====

    def _binarize_roi(self, frame, region):
        """フレームからROIを切り出し、グレースケール2値化画像を返す。"""
        x1, y1, x2, y2 = region
        roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, BINARIZE_THRESHOLD, 255, cv2.THRESH_BINARY_INV)
        return gray, binary

    # ===== 数字認識（テンプレートマッチング） =====

    def read_stat_number(self, frame, region):
        """画面の指定範囲から数値をテンプレートマッチングで読み取る。"""
        _, binary = self._binarize_roi(frame, region)
        return self._read_number_from_roi(binary, self.digit_templates, MATCH_THRESHOLD)

    def read_hp_number(self, frame):
        """HP数値をテンプレートマッチングで読み取る。
        通常テンプレートで試行し、失敗時はHP専用テンプレートでリトライする。
        """
        _, binary = self._binarize_roi(frame, HP_REGION)

        value = self._read_number_from_roi(binary, self.digit_templates, MATCH_THRESHOLD)
        return value

    # ===== 性格読み取り =====

    def read_nature(self):
        """つよさ画面1ページ目から性格名をテンプレートマッチングで読み取る"""
        img = self.camera.readFrame()
        gray, binary = self._binarize_roi(img, NATURE_REGION)

        # 自動テンプレート保存用にROIを保持
        self._nature_roi_gray = gray.copy()

        if not self.nature_templates:
            print('性格テンプレート未登録 → スキップ')
            return None

        best_name = None
        best_score = 0
        for name, template in self.nature_templates.items():
            if template.shape[0] > binary.shape[0] or template.shape[1] > binary.shape[1]:
                continue
            result = cv2.matchTemplate(binary, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_name = name

        if best_name and best_score >= MATCH_THRESHOLD:
            return best_name

        print(f'性格検出失敗（最高スコア: {best_score:.3f}）')

        # 未マッチ画像をディスクに保存（テンプレート収集用）
        if SAVE_UNMATCHED_NATURE:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unmatched_path = os.path.join(self.nature_template_path, f'_unmatched_{timestamp}.png')
            result, encoded = cv2.imencode('.png', self._nature_roi_gray)
            if result:
                encoded.tofile(unmatched_path)

        return None

    def _save_nature_template(self, nature_name):
        """性格テンプレートを自動保存"""
        if self._nature_roi_gray is None:
            return
        path = os.path.join(self.nature_template_path, f'{nature_name}.png')
        result, encoded = cv2.imencode('.png', self._nature_roi_gray)
        if result:
            encoded.tofile(path)
        # キャッシュに追加
        _, binary = cv2.threshold(self._nature_roi_gray, BINARIZE_THRESHOLD, 255, cv2.THRESH_BINARY_INV)
        self.nature_templates[nature_name] = binary

