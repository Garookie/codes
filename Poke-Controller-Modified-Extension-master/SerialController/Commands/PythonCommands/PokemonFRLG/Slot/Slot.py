#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FRLG スロットマシン自動化

前提条件:
- タマムシゲームコーナーのスロットマシンの前でセーブ済み
- コインを所持している

実行フロー:
  初回: スロットマシンに話しかけ → スロット画面へ遷移 → 自動プレイ開始
  リセット時: ソフトリセット → A連打 → あらすじスキップ(B) → スロット画面復帰

テンプレート画像の準備:
  Template/number/ — コイン枚数認識用: 0.png〜9.png
  ../Template/ui/  — 画面検出用: arasuji.png（FRLGBase共通）
"""
from collections import Counter
from datetime import datetime, timezone
import os
import time

from Commands.PythonCommandBase import ImageProcPythonCommand
from Commands.PythonCommands.PokemonFRLG.frlg_base import FRLGBase
from Commands.PythonCommands.settings_manager import SettingsManager
from Commands.Keys import Button, Direction, Stick, Hat

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# ===== 画面座標 (1280x720) =====
COIN_REGION = (470, 110, 595, 160)

# テンプレートマッチング設定
NUMBER_MATCH_THRESHOLD = 0.8
BINARIZE_THRESHOLD = 120
BET_COINS = 3

# 設定ファイル名
SETTING_FILE = 'SlotSetting.ini'
SETTING_SECTION = 'SLOT'

# 区間統計の間隔
PERIOD_SHORT = 10
PERIOD_LONG = 100


class Slot(FRLGBase, ImageProcPythonCommand):
    NAME = '【FRLG】スロットマシン自動化'
    TAGS = ['FRLG']

    def __init__(self, cam, gui=None):
        super().__init__(cam)
        self.gui = gui
        self.template_path_base = os.path.join(os.path.dirname(__file__), 'Template')
        self.number_template_path = os.path.join(self.template_path_base, 'number')
        self.digit_templates = {}
        # 設定ファイル読み込み
        self.settings = SettingsManager(
            setting_name=SETTING_FILE,
            path=os.path.dirname(__file__)
        )
        self._load_settings()

        # 統計
        self.stats = {
            'total_rounds': 0,
            'wins': 0,
            'losses': 0,
            'total_bet': 0,
            'total_payout': 0,
            'roles': {},
            'start_coins': 0,
        }

        # 区間統計（10回転ごと / 100回転ごと）
        self._period_short = {'bet': 0, 'payout': 0}
        self._period_long = {'bet': 0, 'payout': 0, 'roles': {}, 'start_coins': None}

    def _load_settings(self):
        """設定ファイルからデフォルト値を読み込む"""
        if not self.settings.has_section(SETTING_SECTION):
            self.settings.add_section(SETTING_SECTION)
            defaults = {
                'target_coins': 9999,
                'discord_mode': False,
            }
            for key, value in defaults.items():
                self.settings.set(SETTING_SECTION, key, value)

        self.target_coins = self.settings.get_int(SETTING_SECTION, 'target_coins', 9999)
        self.discord_mode = self.settings.get_bool(SETTING_SECTION, 'discord_mode', False)

    def _save_settings(self):
        """現在の設定を設定ファイルに保存"""
        updates = {
            'target_coins': self.target_coins,
            'discord_mode': self.discord_mode,
        }
        for key, value in updates.items():
            self.settings.set(SETTING_SECTION, key, value)

    def set_param(self):
        """GUIダイアログで設定"""
        dialogue_list = [
            ["Entry", "目標コイン枚数（0=無制限）", str(self.target_coins)],
            ["Next"],
            ["Check", "Discord通知", self.discord_mode],
        ]

        ret = self.dialogue6widget("スロットマシン設定", dialogue_list)
        if type(ret) == bool and not ret:
            print("キャンセルされました")
            self.finish()

        self.target_coins = int(ret[0])
        self.discord_mode = ret[1]

        self._save_settings()

        print("------------------------------------")
        print("設定内容:")
        print(f"  目標枚数: {self.target_coins if self.target_coins > 0 else '無制限'}")
        print(f"  Discord通知: {'ON' if self.discord_mode else 'OFF'}")
        print("------------------------------------")

    # ===== テンプレート読み込み =====

    def load_digit_templates(self):
        """数字テンプレートを読み込む"""
        self.digit_templates = self._load_digit_templates(
            self.number_template_path, binarize_mode='fixed', threshold=BINARIZE_THRESHOLD
        )
        loaded = sorted(self.digit_templates.keys())
        missing = [d for d in range(10) if d not in self.digit_templates]
        print(f'数字テンプレート読み込み元: {self.number_template_path}')
        print(f'  読み込み済み: {loaded}')
        if missing:
            print(f'  未登録: {missing}')

    # ===== メインエントリーポイント =====

    def do(self):
        """メインエントリーポイント"""
        self.set_param()

        if not CV2_AVAILABLE:
            print('エラー: OpenCV (cv2) が利用できません')
            self.finish()
            return

        self.load_digit_templates()
        if not self.digit_templates:
            print('エラー: 数字テンプレートが1つもありません')
            self.finish()
            return

        if COIN_REGION == (0, 0, 0, 0):
            print('警告: COIN_REGION が未設定です（コイン枚数読み取り不可）')

        # スロット画面に入る
        self.navigate_to_slot()

        # 初期コイン枚数
        self.wait(1.0)
        initial_coins = self.read_coin_count()
        if initial_coins is not None:
            self.stats['start_coins'] = initial_coins
            self._period_long['start_coins'] = initial_coins
            print(f'初期コイン枚数: {initial_coins}')
        else:
            print('初期コイン枚数: 読み取り不可')

        # output#2にヘッダー出力
        self.print_t2('===== スロット区間統計 =====')
        self.print_t2(f'設定: BET={BET_COINS}')
        self.print_t2(f'{"回転":>6} | {"収支":>8} | {"累計収支":>8} | {"コイン":>8} | {"経過":>5} | {"枚/分":>7}')
        self.print_t2(f'{"-"*6}-+-{"-"*8}-+-{"-"*8}-+-{"-"*8}-+-{"-"*5}-+-{"-"*7}')

        lap = 0
        self.program_start = time.time()
        consecutive_failures = 0
        print('\n--- スロットマシン自動化 開始 ---')

        while True:
            lap += 1

            coins_before = self.read_coin_count()
            if coins_before is not None and coins_before < BET_COINS:
                print(f'\nコイン不足（残り{coins_before}枚）。ソフトリセットします...')
                self.reset_game()
                self.navigate_to_slot()
                consecutive_failures = 0
                continue

            result = self.play_one_round(lap, coins_before)

            if result is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    print(f'\n連続{consecutive_failures}回認識失敗。ソフトリセットします...')
                    self.reset_game()
                    self.navigate_to_slot()
                    consecutive_failures = 0
                continue
            else:
                consecutive_failures = 0

            self.update_stats(result)

            total_rounds = self.stats['total_rounds']

            # 10回転ごとの短期サマリをoutput#2に出力
            if total_rounds % PERIOD_SHORT == 0:
                self.print_period_short(result.get('coins_after'))

            # 100回転ごとの詳細サマリをoutput#2に出力
            if total_rounds % PERIOD_LONG == 0:
                self.print_period_long(result.get('coins_after'))

            if self.target_coins > 0 and result.get('coins_after') is not None:
                if result['coins_after'] >= self.target_coins:
                    print(f'\n★ 目標枚数 {self.target_coins} 達成！（現在: {result["coins_after"]}枚）')
                    break

        total_time = time.time() - self.program_start
        print(f'\n--- スロットマシン自動化 終了 ---')
        print(f'総回転数: {self.stats["total_rounds"]}')
        print(f'総時間: {int(total_time // 60)}分{int(total_time % 60)}秒')
        self.print_stats()

        # 最終区間（端数）もoutput#2に出力
        final_coins = self.read_coin_count()
        total_rounds = self.stats['total_rounds']
        if total_rounds % PERIOD_SHORT != 0:
            self.print_period_short(final_coins)
        if total_rounds % PERIOD_LONG != 0:
            self.print_period_long(final_coins)
        self.print_t2(f'===== 終了 ({total_rounds}回転) =====')

        self.send_notice(embeds=self._build_discord_embeds(total_time))

        self.sleep_switch()

    # ===== 操作系 =====

    def play_one_round(self, lap, coins_before):
        """1回分のスロットプレイ。結果dictを返す"""
        # BET: 方向キー下
        self.pressRep(Hat.BTM, repeat=BET_COINS, duration=0.1, interval=0.3, wait=0.1)

        # A押下×3: 回転開始→左→中→右リール停止
        self.press(Button.A, duration=0.1, wait=0.2)
        self.press(Button.A, duration=0.1, wait=0.8)
        self.press(Button.A, duration=0.1, wait=0.1)

        # 当たり演出をXボタンでスキップ
        self.wait(2.0)
        self.press(Button.X, duration=0.1, wait=1)

        # コイン枚数読み取り
        coins_after = self.read_coin_count()

        # コイン差分で判定
        role_name = '不明'
        payout = 0
        if coins_before is not None and coins_after is not None:
            coin_diff = coins_after - coins_before
            print(f'{lap}回目: コイン {coins_before}→{coins_after} ({coin_diff:+d})')
            if coin_diff > 0:
                role_name = '当たり'
                payout = coin_diff + BET_COINS
            elif coin_diff == 0:
                role_name = 'リプレイ'
                payout = BET_COINS
            else:
                role_name = 'ハズレ'
                payout = 0
        else:
            print(f'{lap}回目: コイン読み取り不可')

        return {
            'role_name': role_name,
            'payout': payout,
            'coins_before': coins_before,
            'coins_after': coins_after,
        }

    def navigate_to_slot(self):
        """ロード後、スロットマシンの前に戻る"""
        self.press(Button.A, duration=0.1, wait=0.5)
        self.press(Button.A, duration=0.1, wait=1.5)
        print('スロットマシンに到着')

    # ===== 認識系 =====

    def read_coin_count(self, frame=None):
        """コイン枚数をテンプレートマッチングで読み取る"""
        if COIN_REGION == (0, 0, 0, 0):
            return None

        if frame is not None:
            return self._read_coin_from_frame(frame)

        # マルチフレーム読み取り（3回）
        results = []
        for _ in range(3):
            f = self.camera.readFrame()
            val = self._read_coin_from_frame(f)
            if val is not None:
                results.append(val)

        if not results:
            return None

        # 最頻値を返す
        most_common = Counter(results).most_common(1)[0]
        return most_common[0]

    def _read_coin_from_frame(self, frame):
        """1フレームからコイン枚数を読み取る"""
        x1, y1, x2, y2 = COIN_REGION
        roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, BINARIZE_THRESHOLD, 255, cv2.THRESH_BINARY)
        return self._read_number_from_roi(binary, self.digit_templates, NUMBER_MATCH_THRESHOLD)

    # ===== 統計 =====

    def update_stats(self, result):
        """統計を更新する"""
        self.stats['total_rounds'] += 1
        self.stats['total_bet'] += BET_COINS

        role_name = result.get('role_name', '不明')
        payout = result.get('payout', 0)

        self.stats['total_payout'] += payout
        self._period_short['bet'] += BET_COINS
        self._period_short['payout'] += payout
        self._period_long['bet'] += BET_COINS
        self._period_long['payout'] += payout

        if role_name not in ('ハズレ', '不明', '認識失敗'):
            self.stats['wins'] += 1
        else:
            self.stats['losses'] += 1

        if role_name not in self.stats['roles']:
            self.stats['roles'][role_name] = 0
        self.stats['roles'][role_name] += 1

        roles = self._period_long['roles']
        if role_name not in roles:
            roles[role_name] = 0
        roles[role_name] += 1

    def _elapsed_stats(self):
        """経過時間と収支レートを計算する"""
        elapsed = time.time() - self.program_start
        elapsed_m, elapsed_s = divmod(int(elapsed), 60)
        elapsed_str = f'{elapsed_m}:{elapsed_s:02d}'
        total_net = self.stats['total_payout'] - self.stats['total_bet']
        rate = total_net / (elapsed / 60) if elapsed > 0 else None
        return elapsed_str, total_net, rate

    def _reset_period_short(self):
        self._period_short = {'bet': 0, 'payout': 0}

    def _reset_period_long(self, current_coins=None):
        self._period_long = {'bet': 0, 'payout': 0, 'roles': {}, 'start_coins': current_coins}

    def print_period_short(self, current_coins):
        """10回転ごとの短期サマリをoutput#2に出力"""
        total = self.stats['total_rounds']
        period_net = self._period_short['payout'] - self._period_short['bet']
        coins_str = str(current_coins) if current_coins is not None else '?'
        elapsed_str, total_net, rate = self._elapsed_stats()
        rate_str = f'{rate:>+7.1f}' if rate is not None else f'{"-":>7}'
        self.print_t2(f'{total:>6} | {period_net:>+8} | {total_net:>+8} | {coins_str:>8} | {elapsed_str:>5} | {rate_str}')
        self._reset_period_short()

    def print_period_long(self, current_coins):
        """100回転ごとの詳細サマリをoutput#2に出力"""
        total = self.stats['total_rounds']
        period_net = self._period_long['payout'] - self._period_long['bet']
        coins_str = str(current_coins) if current_coins is not None else '?'
        elapsed_str, total_net, rate = self._elapsed_stats()
        rate_str = f'{rate:+.1f}' if rate is not None else '-'

        self.print_t2(f'--- {total}回転 まとめ ---')
        self.print_t2(f'  区間収支: {period_net:+d} / 累計収支: {total_net:+d} / コイン: {coins_str}')
        self.print_t2(f'  経過: {elapsed_str} / コイン/分: {rate_str}')

        roles = self._period_long['roles']
        if roles:
            roles_parts = [f'{role}:{count}'
                           for role, count in sorted(roles.items(), key=lambda x: -x[1])]
            self.print_t2(f'  役: {", ".join(roles_parts)}')

        self.print_t2(f'{"-"*6}-+-{"-"*8}-+-{"-"*8}-+-{"-"*8}-+-{"-"*5}-+-{"-"*7}')
        self._reset_period_long(current_coins)

    def print_stats(self):
        """現在の統計をログ出力する"""
        s = self.stats
        total = s['total_rounds']
        if total == 0:
            return

        win_rate = s['wins'] / total * 100
        net = s['total_payout'] - s['total_bet']

        print('\n========== 統計 ==========')
        print(f'総回転数: {total}')
        print(f'勝利: {s["wins"]} / 敗北: {s["losses"]} (勝率: {win_rate:.1f}%)')
        print(f'総BET: {s["total_bet"]} / 総払出: {s["total_payout"]} / 収支: {net:+d}')

        if s['roles']:
            print('--- 役別出現回数 ---')
            for role, count in sorted(s['roles'].items(), key=lambda x: -x[1]):
                rate = count / total * 100
                print(f'  {role}: {count}回 ({rate:.1f}%)')

        print('==========================\n')

    def _build_discord_embeds(self, total_time):
        """Discord通知用のembedsを構築して返す"""
        s = self.stats
        total = s['total_rounds']
        if total == 0:
            return None

        win_rate = s['wins'] / total * 100
        net = s['total_payout'] - s['total_bet']
        minutes = int(total_time // 60)
        seconds = int(total_time % 60)

        # 収支に応じた動的カラー
        if net > 0:
            color = 0x00C853   # 緑 = 黒字
        elif net < 0:
            color = 0xF44336   # 赤 = 赤字
        else:
            color = 0x9E9E9E   # グレー = ±0

        # 役別テキスト（コードブロック + %表示）
        if s['roles']:
            lines = []
            for role, count in sorted(s['roles'].items(), key=lambda x: -x[1]):
                rate = count / total * 100
                lines.append(f'{role}: {count}回 ({rate:.1f}%)')
            roles_text = '```\n' + '\n'.join(lines) + '\n```'
        else:
            roles_text = 'なし'

        # コイン/分レート
        rate = net / (total_time / 60) if total_time > 0 else 0
        rate_str = f'{rate:+.1f}枚/分'

        return [{
            'title': '【FRLG】スロット自動化 結果',
            'description': f'勝利 {s["wins"]} / 敗北 {s["losses"]}',
            'color': color,
            'fields': [
                {'name': '総回転数', 'value': f'`{total}`回', 'inline': True},
                {'name': '勝率', 'value': f'**{win_rate:.1f}%**', 'inline': True},
                {'name': '収支', 'value': f'**{net:+d}枚**', 'inline': True},
                {'name': '所要時間', 'value': f'{minutes}分{seconds}秒', 'inline': True},
                {'name': '役別', 'value': roles_text, 'inline': False},
            ],
            'footer': {'text': f'レート: {rate_str}'},
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        }]