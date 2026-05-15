from Commands.Keys import Button
import os
import time
import cv2
import numpy as np

RESET_MAX_RETRIES = 3
RESET_TITLE_TIMEOUT = 10
RESET_FIELD_TIMEOUT = 10
TEMPLATE_THRESHOLD = 0.8
FIELD_DETECT_CROP = [60, 690, 335, 705]  # crop_fmt=1: [x1, y1, x2, y2]
LOADING_BRIGHTNESS_THRESHOLD = 40  # これ以下なら黒画面（ロード中）と判定
CALORIE_ROI = (50, 85, 145, 120)  # 異次元ミアレ用カロリーROI（ペイント座標 x1,y1,x2,y2）
CALORIE_BINARIZE_THRESHOLD = 127
CALORIE_DIGIT_COMPONENT_MIN_AREA = 20
CALORIE_DIGIT_COMPONENT_MAX_AREA = 700
CALORIE_DIGIT_COMPONENT_MIN_WIDTH = 2
CALORIE_DIGIT_COMPONENT_MAX_WIDTH = 28
CALORIE_DIGIT_COMPONENT_MIN_HEIGHT = 10
CALORIE_DIGIT_COMPONENT_MAX_HEIGHT = 35
CALORIE_DIGIT_CANDIDATE_MIN_AREA = 100
CALORIE_DIGIT_CANDIDATE_MAX_AREA = 520
CALORIE_DIGIT_CANDIDATE_MIN_WIDTH = 5
CALORIE_DIGIT_CANDIDATE_MAX_WIDTH = 24
CALORIE_DIGIT_CANDIDATE_MIN_HEIGHT = 22
CALORIE_DIGIT_CANDIDATE_MAX_HEIGHT = 34
CALORIE_DIGIT_CLASSIFY_MIN_SCORE = 0.45
CALORIE_CONFIRM_READS = 2
CALORIE_CONFIRM_INTERVAL = 0.25
CALORIE_MIN_CONFIRM_LOW_READS = 2
CALORIE_MIN_STOP_DIGITS = 3
CALORIE_SUSPICIOUS_DROP_KCAL = 300
CALORIE_LEADING_COMPONENT_MARGIN = 1

ZA_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'Template')
TITLE_TEMPLATE = os.path.join(ZA_TEMPLATE_DIR, 'title.png')
FIELD_TEMPLATE = os.path.join(ZA_TEMPLATE_DIR, 'field.png')
FIELD_REVERSE_TEMPLATE = os.path.join(ZA_TEMPLATE_DIR, 'field_reverse.png')
FIELD_TEMPLATES = (FIELD_TEMPLATE, FIELD_REVERSE_TEMPLATE)
FIELD_TEMPLATE_CANDIDATES = (
    (FIELD_TEMPLATE, 'field'),
    (FIELD_REVERSE_TEMPLATE, 'field_reverse'),
)
MAP_TEMPLATE = os.path.join(ZA_TEMPLATE_DIR, 'map.png')
ZA_DIGIT_TEMPLATE_DIR = os.path.join(ZA_TEMPLATE_DIR, 'digits')


class ZAUtilsMixin:
    """PokemonZA 共通ユーティリティ Mixin。
    ImageProcPythonCommand 系クラスに追加継承させて使う
    （CommonMixin 経由で sleep_switch が利用可能）。
    """

    def soft_reboot(self):
        """ソフトリセット → タイトル検出 → A → フィールド復帰確認（Switch 2方式、最大3回リトライ）。"""
        for attempt in range(RESET_MAX_RETRIES):
            if attempt > 0:
                print(f"soft_reboot retry ({attempt}/{RESET_MAX_RETRIES - 1})")

            self.press(Button.HOME, wait=1.0)
            self.press(Button.X, wait=1.0)

            title_found = False
            title_start = time.time()
            while time.time() - title_start < RESET_TITLE_TIMEOUT:
                if self.isContainTemplate(TITLE_TEMPLATE, threshold=TEMPLATE_THRESHOLD):
                    self.press(Button.A, wait=0.5)
                    title_found = True
                    break
                self.press(Button.A, wait=0.5)

            if not title_found:
                print(f"警告: タイトル検出タイムアウト（{RESET_TITLE_TIMEOUT}秒）")
                continue

            self.press(Button.A, wait=0.5)

            if self.wait_for_field(timeout=RESET_FIELD_TIMEOUT):
                return True

        print("ERROR: soft_reboot - all retries failed")
        self.sleep_switch()
        return False

    def is_field(self, threshold=0.95):
        """通常向き/逆向きどちらかのフィールド表示を検出する。"""
        for template in FIELD_TEMPLATES:
            if os.path.exists(template) and self.isContainTemplate(
                template, threshold=threshold, crop_fmt=1, crop=FIELD_DETECT_CROP
            ):
                return True
        return False

    def wait_for_field(self, timeout=10, threshold=0.95):
        """通常向き/逆向きのテンプレートマッチによるフィールド復帰検出。
        検出できたら True、タイムアウトで False（警告メッセージ出力）。
        """
        start = time.time()
        while time.time() - start < timeout:
            if self.is_field(threshold=threshold):
                return True
            self.wait(0.5)
        print(f"警告: フィールド復帰検出タイムアウト（{timeout}秒）")
        return False

    def open_map(self, timeout=30, template=None):
        """PLUS を押して MAP 画面が開くまで待機する。
        検出できたら True、タイムアウトで False（警告メッセージ出力）。
        template に画像パスを渡せば検出テンプレートを切替可能（例: 異次元ミアレの wild_dimension.png）。
        """
        if template is None:
            template = MAP_TEMPLATE
        start = time.time()
        while time.time() - start < timeout:
            self.press(Button.PLUS, wait=0.5)
            if self.isContainTemplate(template, threshold=TEMPLATE_THRESHOLD):
                return True
        print("警告: MAP表示検出タイムアウト")
        return False

    def is_loading(self):
        """画面左上半分の平均輝度が閾値以下（＝ロード中の黒画面）か判定"""
        frame = self.camera.readFrame()
        if frame is None:
            return False
        h, w = frame.shape[:2]
        region = frame[0:h // 2, 0:w // 2]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        return np.mean(gray) < LOADING_BRIGHTNESS_THRESHOLD

    def _load_digit_templates(self, template_dir, binarize_mode, threshold):
        """数字テンプレート画像(0.png〜9.png)を読み込み2値化して返す（read_number_from_roi 内部用）。"""
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

    def read_number_from_roi(self, binary_image, template_dir=None, binarize_mode='fixed_inv',
                             binarize_threshold=127, match_threshold=0.8, group_distance=15):
        """2値化済みROI画像から数字テンプレートマッチングで数値を読み取る。
        テンプレートは初回のみロードしてインスタンスにキャッシュする。
        """
        detail = self.read_number_from_roi_detailed(
            binary_image,
            template_dir=template_dir,
            binarize_mode=binarize_mode,
            binarize_threshold=binarize_threshold,
            match_threshold=match_threshold,
            group_distance=group_distance,
        )
        return detail['value']

    def read_number_from_roi_detailed(self, binary_image, template_dir=None, binarize_mode='fixed_inv',
                                      binarize_threshold=127, match_threshold=0.8, group_distance=15):
        """数値に加えて、認識桁数や数字成分の位置情報を返す。

        低カロリー誤検知のような桁落ち判定で使うため、read_number_from_roi の
        互換動作は維持しつつ詳細情報だけを追加で取得できるようにする。
        """
        if template_dir is None:
            template_dir = ZA_DIGIT_TEMPLATE_DIR

        components = self._extract_digit_components(binary_image)
        digit_candidates, rejected_components = self._filter_calorie_digit_candidates(components)
        detail = {
            'value': None,
            'number_text': '',
            'digit_count': 0,
            'component_count': len(components),
            'components': components,
            'digit_candidates': digit_candidates,
            'digit_candidate_count': len(digit_candidates),
            'rejected_components': rejected_components,
            'rejected_component_count': len(rejected_components),
            'groups': [],
            'digit_scores': [],
            'min_digit_score': None,
            'match_count': 0,
            'method': None,
        }

        cache_key = (template_dir, binarize_mode, binarize_threshold)
        if not hasattr(self, '_digit_templates_cache'):
            self._digit_templates_cache = {}
        if cache_key not in self._digit_templates_cache:
            self._digit_templates_cache[cache_key] = self._load_digit_templates(
                template_dir, binarize_mode, binarize_threshold,
            )
        digit_templates = self._digit_templates_cache[cache_key]

        if not digit_templates:
            return detail

        if self._read_number_by_digit_components(binary_image, digit_templates, digit_candidates, detail):
            return detail

        matches = []
        for digit, tmpl in digit_templates.items():
            th, tw = tmpl.shape[:2]
            if th > binary_image.shape[0] or tw > binary_image.shape[1]:
                continue
            result = cv2.matchTemplate(binary_image, tmpl, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= match_threshold)
            for pt_y, pt_x in zip(*locations):
                score = result[pt_y, pt_x]
                matches.append((pt_x, digit, score))

        detail['match_count'] = len(matches)
        if not matches:
            return detail

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
        detail['number_text'] = number_str
        detail['digit_count'] = len(grouped)
        detail['groups'] = grouped
        digit_scores = [g['score'] for g in grouped]
        detail['digit_scores'] = digit_scores
        detail['min_digit_score'] = min(digit_scores) if digit_scores else None
        detail['method'] = 'template_scan'

        try:
            detail['value'] = int(number_str)
        except ValueError:
            detail['value'] = None
        return detail

    def _filter_calorie_digit_candidates(self, components):
        """数字テンプレート相当のサイズだけを桁候補として残す。"""
        digit_candidates = []
        rejected_components = []
        for component in components:
            area = component['area']
            width = component['width']
            height = component['height']
            if (
                CALORIE_DIGIT_CANDIDATE_MIN_AREA <= area <= CALORIE_DIGIT_CANDIDATE_MAX_AREA and
                CALORIE_DIGIT_CANDIDATE_MIN_WIDTH <= width <= CALORIE_DIGIT_CANDIDATE_MAX_WIDTH and
                CALORIE_DIGIT_CANDIDATE_MIN_HEIGHT <= height <= CALORIE_DIGIT_CANDIDATE_MAX_HEIGHT
            ):
                digit_candidates.append(component)
            else:
                rejected_components.append(component)

        digit_candidates.sort(key=lambda component: component['x'])
        rejected_components.sort(key=lambda component: component['x'])
        return digit_candidates, rejected_components

    def _read_number_by_digit_components(self, binary_image, digit_templates, digit_candidates, detail):
        """連結成分で切り出した各桁をテンプレート分類して数値化する。"""
        if not digit_candidates:
            return False

        groups = []
        for component in digit_candidates:
            digit, score = self._classify_digit_component(binary_image, component, digit_templates)
            if digit is None or score < CALORIE_DIGIT_CLASSIFY_MIN_SCORE:
                return False
            group = {
                'x': component['x'],
                'digit': digit,
                'score': score,
                'width': component['width'],
                'height': component['height'],
            }
            groups.append(group)

        groups.sort(key=lambda group: group['x'])
        number_str = ''.join(str(group['digit']) for group in groups)
        try:
            value = int(number_str)
        except ValueError:
            return False

        detail['value'] = value
        detail['number_text'] = number_str
        detail['digit_count'] = len(groups)
        detail['groups'] = groups
        digit_scores = [group['score'] for group in groups]
        detail['digit_scores'] = digit_scores
        detail['min_digit_score'] = min(digit_scores) if digit_scores else None
        detail['match_count'] = len(groups)
        detail['method'] = 'component_classify'
        return True

    def _classify_digit_component(self, binary_image, component, digit_templates):
        """1つの数字候補を0〜9テンプレートのどれに近いか分類する。"""
        x = component['x']
        y = component['y']
        width = component['width']
        height = component['height']
        crop = binary_image[y:y + height, x:x + width]
        if crop.size == 0:
            return None, 0.0

        best_digit = None
        best_score = -1.0
        for digit, tmpl in digit_templates.items():
            tmpl_crop = self._crop_digit_foreground(tmpl)
            th, tw = tmpl_crop.shape[:2]
            resized = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_NEAREST)
            score = float(cv2.matchTemplate(resized, tmpl_crop, cv2.TM_CCOEFF_NORMED)[0, 0])
            if score > best_score:
                best_digit = digit
                best_score = score

        return best_digit, best_score

    def _crop_digit_foreground(self, binary_image):
        """数字の前景外接矩形でテンプレート余白を落とす。"""
        foreground = cv2.bitwise_not(binary_image)
        component_count, _labels, stats, _ = cv2.connectedComponentsWithStats(foreground, 8)
        if component_count <= 1:
            return binary_image

        label = max(range(1, component_count), key=lambda idx: stats[idx, cv2.CC_STAT_AREA])
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        return binary_image[y:y + height, x:x + width]

    def _extract_digit_components(self, binary_image):
        """2値化済みROI内の数字らしい連結成分を位置情報つきで返す。"""
        foreground = cv2.bitwise_not(binary_image)
        kernel = np.ones((2, 2), np.uint8)
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, kernel)
        component_count, _labels, stats, _ = cv2.connectedComponentsWithStats(foreground, 8)

        components = []
        for label in range(1, component_count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            width = int(stats[label, cv2.CC_STAT_WIDTH])
            height = int(stats[label, cv2.CC_STAT_HEIGHT])
            if (
                CALORIE_DIGIT_COMPONENT_MIN_AREA <= area <= CALORIE_DIGIT_COMPONENT_MAX_AREA and
                CALORIE_DIGIT_COMPONENT_MIN_WIDTH <= width <= CALORIE_DIGIT_COMPONENT_MAX_WIDTH and
                CALORIE_DIGIT_COMPONENT_MIN_HEIGHT <= height <= CALORIE_DIGIT_COMPONENT_MAX_HEIGHT
            ):
                components.append({
                    'x': x,
                    'y': y,
                    'width': width,
                    'height': height,
                    'area': area,
                })

        components.sort(key=lambda component: component['x'])
        return components

    def _count_digit_components(self, binary_image):
        """2値化済みROI内の数字らしい連結成分数を数える。"""
        return len(self._extract_digit_components(binary_image))

    def read_calorie_detail(self):
        """画面左上のカロリー数値を詳細情報つきで読み取る（異次元ミアレ用）。"""
        frame = self.camera.readFrame()
        empty_detail = {
            'value': None,
            'number_text': '',
            'digit_count': 0,
            'component_count': 0,
            'components': [],
            'digit_candidates': [],
            'digit_candidate_count': 0,
            'rejected_components': [],
            'rejected_component_count': 0,
            'groups': [],
            'digit_scores': [],
            'min_digit_score': None,
            'match_count': 0,
            'method': None,
        }
        if frame is None:
            return empty_detail

        x1, y1, x2, y2 = CALORIE_ROI
        roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, CALORIE_BINARIZE_THRESHOLD, 255, cv2.THRESH_BINARY_INV)
        detail = self.read_number_from_roi_detailed(
            binary,
            binarize_mode='fixed_inv',
            binarize_threshold=CALORIE_BINARIZE_THRESHOLD,
        )
        if detail['value'] is None:
            print('警告: カロリー読み取り失敗')
        return detail

    def read_calorie(self):
        """画面左上のカロリー数値を読み取る（異次元ミアレ用）。
        フレーム取得 → ROI切り出し → グレー化 → 2値化 → 数字テンプレートマッチングを実行。
        失敗時は警告を出して None を返す。
        """
        return self.read_calorie_detail()['value']

    def reset_calorie_tracking(self):
        """カロリー誤検知対策で使う直前の信頼値をリセットする。"""
        self._last_reliable_calorie = None

    def confirm_calorie_target(self, target_calorie, continue_message='移動を継続します'):
        """カロリーが目標以下かを誤検知ガード付きで確認する。

        目標到達と判断できる場合は確認済み detail、誤読疑いまたは目標超過なら None を返す。
        """
        detail = self.read_calorie_detail()
        calorie = detail['value']
        if calorie is None:
            print(f'警告: カロリーを確認できないため{continue_message}')
            return None

        self._print_calorie_detail(detail, target_calorie)
        if self._is_calorie_low_digit_suspected(detail, target_calorie):
            print(f'警告: カロリー認識桁数が少なすぎるため{continue_message}')
            return None
        if self._is_calorie_digit_drop_suspected(detail, target_calorie):
            print(f'警告: カロリーの桁落ち疑いがあるため{continue_message}')
            return None
        if self._is_calorie_suspicious_drop(detail, target_calorie):
            print(f'警告: 直前カロリーからの低下幅が不自然なため{continue_message}')
            return None

        if calorie > target_calorie:
            self._remember_reliable_calorie(detail, target_calorie)
            return None

        return self._confirm_target_calorie_reads(detail, target_calorie, continue_message)

    def _confirm_target_calorie_reads(self, first_detail, target_calorie, continue_message):
        if self._is_calorie_low_digit_suspected(first_detail, target_calorie):
            print('警告: 初回カロリーの認識桁数が少なすぎるため停止しません')
            return None

        details = [first_detail]
        for _ in range(CALORIE_CONFIRM_READS - 1):
            self.wait(CALORIE_CONFIRM_INTERVAL)
            detail = self.read_calorie_detail()
            calorie = detail['value']
            if calorie is None:
                print('警告: カロリー再確認に失敗しました')
                continue

            self._print_calorie_detail(detail, target_calorie, prefix='再確認カロリー')
            if self._is_calorie_low_digit_suspected(detail, target_calorie):
                print('警告: カロリー再確認で認識桁数が少なすぎるため停止しません')
                return None
            if self._is_calorie_digit_drop_suspected(detail, target_calorie):
                print('警告: カロリー再確認で桁落ち疑いを検出したため停止しません')
                return None
            if calorie > target_calorie:
                print('警告: カロリー再確認で目標超過を検出したため停止しません')
                self._remember_reliable_calorie(detail, target_calorie)
                return None
            if self._is_calorie_suspicious_drop(detail, target_calorie, baseline_detail=details[-1]):
                print('警告: カロリー再確認で不自然な急落を検出したため停止しません')
                return None

            details.append(detail)

        valid_details = [d for d in details if d['value'] is not None]
        low_details = [d for d in valid_details if self._is_confirmed_low_calorie(d, target_calorie)]
        if len(low_details) < CALORIE_MIN_CONFIRM_LOW_READS:
            print(f'警告: 目標カロリーの確認回数が不足したため{continue_message}')
            return None
        if len(low_details) <= len(valid_details) / 2:
            print(f'警告: 目標カロリー以下の読み取りが過半数でないため{continue_message}')
            return None

        return low_details[-1]

    def _print_calorie_detail(self, detail, target_calorie, prefix='残りカロリー'):
        calorie = detail['value']
        min_score = detail.get('min_digit_score')
        min_score_text = f'{min_score:.2f}' if min_score is not None else '-'
        print(
            f'{prefix}: {calorie}kcal (目標: {target_calorie}kcal以下, '
            f'認識文字: {detail.get("number_text", "")}, '
            f'OCR: {detail.get("method") or "unknown"}, '
            f'認識桁数: {detail["digit_count"]}, 数字成分数: {detail["component_count"]}, '
            f'数字候補数: {detail.get("digit_candidate_count", len(detail.get("digit_candidates") or []))}, '
            f'除外成分数: {detail.get("rejected_component_count", len(detail.get("rejected_components") or []))}, '
            f'最小スコア: {min_score_text})'
        )

    def _is_calorie_low_digit_suspected(self, detail, target_calorie):
        calorie = detail['value']
        if calorie is None or calorie > target_calorie:
            return False
        return detail.get('digit_count', 0) < CALORIE_MIN_STOP_DIGITS

    def _is_confirmed_low_calorie(self, detail, target_calorie):
        calorie = detail['value']
        if calorie is None or calorie > target_calorie:
            return False
        return detail.get('digit_count', 0) >= CALORIE_MIN_STOP_DIGITS

    def _is_calorie_digit_drop_suspected(self, detail, target_calorie):
        calorie = detail['value']
        if calorie is None or calorie > target_calorie:
            return False

        groups = detail.get('groups') or []
        components = detail.get('components') or []
        if not groups or not components:
            return False

        first_digit_x = min(group['x'] for group in groups)
        for component in components:
            component_right = component['x'] + component['width']
            if component_right <= first_digit_x - CALORIE_LEADING_COMPONENT_MARGIN:
                return True
        return False

    def _is_calorie_suspicious_drop(self, detail, target_calorie, baseline_detail=None):
        last_calorie = getattr(self, '_last_reliable_calorie', None)
        calorie = detail['value']
        if baseline_detail is not None:
            last_calorie = baseline_detail.get('value')
        if last_calorie is None or calorie is None:
            return False
        if calorie > target_calorie or calorie >= last_calorie:
            return False
        return last_calorie - calorie > CALORIE_SUSPICIOUS_DROP_KCAL

    def _remember_reliable_calorie(self, detail, target_calorie):
        calorie = detail['value']
        if calorie is not None and calorie > target_calorie:
            self._last_reliable_calorie = calorie
