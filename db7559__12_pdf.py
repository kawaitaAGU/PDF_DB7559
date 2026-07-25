import streamlit as st
import pandas as pd
import io
import requests
from PIL import Image
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
import time
from pathlib import Path
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import re

# ---- フォント設定（IPAex を優先、無ければCIDフォントへフォールバック）----
def _setup_font():
    here = Path(__file__).parent
    candidates = [
        here / "fonts" / "IPAexGothic.ttf",
        here / "IPAexGothic.ttf",
        Path.cwd() / "fonts" / "IPAexGothic.ttf",
        Path.cwd() / "IPAexGothic.ttf",
    ]
    for p in candidates:
        if p.exists():
            pdfmetrics.registerFont(TTFont("Japanese", str(p)))
            return "Japanese"
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    return "HeiseiKakuGo-W5"

JAPANESE_FONT = _setup_font()

# ---- 追加フォント（アラビア文字など日本語フォントに無い文字用のフォールバック）----
def _setup_fallback_font():
    here = Path(__file__).parent
    candidates = [
        here / "fonts" / "Unifont.otf",
        here / "fonts" / "DejaVuSans.ttf",
        Path.cwd() / "fonts" / "Unifont.otf",
        Path.cwd() / "fonts" / "DejaVuSans.ttf",
    ]
    for i, p in enumerate(candidates):
        if p.exists():
            try:
                name = f"Fallback{i}"
                pdfmetrics.registerFont(TTFont(name, str(p)))
                return name
            except Exception:
                continue
    return None

FALLBACK_FONT = _setup_fallback_font()

# ---- アラビア文字の連結表示・右→左の表示順を補正 ----
try:
    import arabic_reshaper
    from bidi.algorithm import get_display as _bidi_display
except ImportError:
    arabic_reshaper = None
    _bidi_display = None

_ARABIC_RE = re.compile(r'[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]')

def _shape_arabic(text: str) -> str:
    """アラビア文字が含まれる場合のみ、文字の連結（reshape）と表示順（bidi）を整える"""
    if not text or arabic_reshaper is None or not _ARABIC_RE.search(text):
        return text
    try:
        return _bidi_display(arabic_reshaper.reshape(text))
    except Exception:
        return text

def _split_font_runs(text: str):
    """文字列をアラビア文字とそれ以外のランに分割し、それぞれの描画フォントを決める"""
    if not text or FALLBACK_FONT is None:
        return [(JAPANESE_FONT, text or "")]
    runs = []
    buf, cur_is_arabic = "", None
    for ch in text:
        is_arabic = bool(_ARABIC_RE.match(ch))
        if cur_is_arabic is None:
            cur_is_arabic = is_arabic
        if is_arabic != cur_is_arabic:
            runs.append((FALLBACK_FONT if cur_is_arabic else JAPANESE_FONT, buf))
            buf, cur_is_arabic = "", is_arabic
        buf += ch
    if buf:
        runs.append((FALLBACK_FONT if cur_is_arabic else JAPANESE_FONT, buf))
    return runs

def _text_width(text: str, font_size: int) -> float:
    return sum(stringWidth(chunk, font, font_size) for font, chunk in _split_font_runs(text) if chunk)

st.set_page_config(
    page_title="Dental Exam Archive",
    page_icon="🦷",
    layout="wide",
)

# ===== ウェルカム画面 =====
# 認証画面ではなく、検索データベースへ入る前の入口ページ。
# 旧版の検索・CSV・TEXT・GoodNotes・画像付きPDF機能には手を加えない。
if "welcome_entered" not in st.session_state:
    st.session_state["welcome_entered"] = False

if not st.session_state["welcome_entered"]:
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 50% 42%, rgba(65, 208, 255, .13), transparent 26rem),
                radial-gradient(circle at 12% 78%, rgba(244, 184, 69, .08), transparent 20rem),
                linear-gradient(180deg, #07101d 0%, #0b1624 58%, #09101a 100%);
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        footer {
            display: none;
        }

        .block-container {
            max-width: 1180px;
            padding-top: 2.5vh;
            padding-bottom: 3vh;
        }

        .welcome-shell {
            min-height: 76vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: #f9f5e9;
            text-align: center;
        }

        .welcome-kicker {
            display: inline-flex;
            align-items: center;
            gap: .55rem;
            padding: .5rem .85rem;
            border: 1px solid rgba(235, 196, 119, .25);
            border-radius: 999px;
            background: rgba(24, 38, 55, .82);
            color: #e6ca91;
            font-size: .78rem;
            font-weight: 700;
            letter-spacing: .14em;
        }

        .library-scene {
            position: relative;
            width: min(930px, 96vw);
            height: clamp(285px, 37vw, 410px);
            margin: 1.35rem auto 1.1rem;
            overflow: hidden;
            border: 1px solid rgba(189, 151, 82, .18);
            border-radius: 28px;
            background:
                linear-gradient(90deg, rgba(4, 10, 17, .64), transparent 24%, transparent 76%, rgba(4, 10, 17, .64)),
                linear-gradient(180deg, #111e2d 0%, #0c1723 72%, #11151b 72%, #080c12 100%);
            box-shadow:
                inset 0 -40px 70px rgba(0, 0, 0, .48),
                0 34px 80px rgba(0, 0, 0, .38);
        }

        .library-scene::before,
        .library-scene::after {
            content: "";
            position: absolute;
            top: 0;
            bottom: 26%;
            width: 25%;
            background:
                repeating-linear-gradient(180deg, transparent 0 47px, #6d4b2d 48px 53px),
                repeating-linear-gradient(90deg, #314059 0 13px, #8b5530 14px 22px, #22344d 23px 36px, #a07846 37px 43px);
            opacity: .8;
            box-shadow: inset 0 0 30px rgba(0, 0, 0, .65);
        }

        .library-scene::before {
            left: 0;
        }

        .library-scene::after {
            right: 0;
        }

        .window-moon {
            position: absolute;
            top: 7%;
            left: 50%;
            width: 92px;
            height: 116px;
            transform: translateX(-50%);
            border: 5px solid #273c50;
            border-radius: 48px 48px 4px 4px;
            background:
                radial-gradient(circle at 68% 30%, #fff5bc 0 11px, #e9c871 12px 16px, transparent 17px),
                linear-gradient(180deg, #09152c, #142749);
            box-shadow:
                0 0 26px rgba(127, 182, 232, .14),
                inset 0 0 18px rgba(0, 0, 0, .5);
        }

        .tooth-gate {
            position: absolute;
            z-index: 3;
            top: 19%;
            left: 50%;
            width: clamp(120px, 18vw, 175px);
            height: clamp(150px, 23vw, 220px);
            transform: translateX(-50%);
            display: grid;
            place-items: center;
            border: 2px solid rgba(141, 236, 255, .48);
            border-radius: 80px 80px 35px 35px;
            background:
                radial-gradient(circle at 50% 46%, rgba(158, 244, 255, .44), transparent 48%),
                linear-gradient(160deg, rgba(22, 94, 118, .88), rgba(7, 37, 56, .94));
            box-shadow:
                inset 0 0 32px rgba(134, 242, 255, .42),
                0 0 24px rgba(71, 207, 237, .42),
                0 0 70px rgba(71, 207, 237, .25);
        }

        .tooth-gate::before {
            content: "🦷";
            font-size: clamp(4.2rem, 9vw, 7rem);
            filter:
                drop-shadow(0 0 8px #d9fbff)
                drop-shadow(0 0 22px #67dcef);
        }

        .tooth-gate::after {
            content: "知識の書庫";
            position: absolute;
            bottom: 11px;
            color: #bff5ff;
            font-family: "Hiragino Mincho ProN", "Yu Mincho", serif;
            font-size: .72rem;
            letter-spacing: .16em;
        }

        .floor-light {
            position: absolute;
            z-index: 2;
            left: 50%;
            bottom: 2%;
            width: 48%;
            height: 28%;
            transform: translateX(-50%);
            background: linear-gradient(180deg, rgba(72, 212, 238, .22), transparent 76%);
            clip-path: polygon(36% 0, 64% 0, 100% 100%, 0 100%);
            filter: blur(2px);
        }

        .library-desk {
            position: absolute;
            z-index: 4;
            left: 6%;
            right: 6%;
            bottom: 13%;
            height: 15px;
            border-radius: 7px;
            background: linear-gradient(180deg, #9c6c38, #50331e);
            box-shadow: 0 10px 0 #2e1d14, 0 20px 22px rgba(0, 0, 0, .45);
        }

        .library-friends {
            position: absolute;
            z-index: 6;
            left: 8%;
            right: 8%;
            bottom: calc(13% + 15px);
            display: flex;
            justify-content: space-between;
            align-items: end;
            pointer-events: none;
        }

        .friend {
            position: relative;
            width: clamp(72px, 11vw, 112px);
            height: clamp(96px, 14vw, 138px);
            display: grid;
            place-items: center;
            border: 2px solid rgba(255, 255, 255, .12);
            border-radius: 42px 42px 28px 28px;
            box-shadow:
                inset 0 -20px 26px rgba(0, 0, 0, .25),
                0 14px 20px rgba(0, 0, 0, .28);
        }

        .friend::after {
            content: "";
            position: absolute;
            bottom: 20%;
            width: 34%;
            height: 5px;
            border-radius: 999px;
            background: rgba(6, 17, 28, .72);
        }

        .toothbrush-friend {
            background: linear-gradient(160deg, #63d1d0, #216d80);
        }

        .book-friend {
            background: linear-gradient(160deg, #ec9b58, #994926);
        }

        .mirror-friend {
            background: linear-gradient(160deg, #a38bd8, #514382);
        }

        .friend-icon {
            transform: translateY(-8%);
            font-size: clamp(2.7rem, 6vw, 4.7rem);
            filter: drop-shadow(0 7px 5px rgba(0, 0, 0, .28));
        }

        .mirror-tool {
            position: relative;
            width: clamp(46px, 6vw, 64px);
            height: clamp(64px, 8vw, 88px);
            transform: rotate(-18deg) translateY(-5%);
        }

        .mirror-tool::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 68%;
            aspect-ratio: 1;
            border: 5px solid #d7eef4;
            border-radius: 50%;
            background: radial-gradient(circle at 35% 30%, #f7ffff, #85bdcf 52%, #426f85);
            box-shadow: 0 0 17px rgba(186, 240, 255, .55);
        }

        .mirror-tool::after {
            content: "";
            position: absolute;
            top: 42%;
            left: 31%;
            width: 8px;
            height: 59%;
            border-radius: 999px;
            background: linear-gradient(90deg, #c8dce2, #758e9a);
        }

        .welcome-title {
            margin: .2rem 0 .65rem;
            font-family: "Hiragino Mincho ProN", "Yu Mincho", serif;
            font-size: clamp(2.3rem, 5vw, 4.4rem);
            font-weight: 700;
            line-height: 1.18;
            letter-spacing: -.035em;
            text-shadow: 0 8px 32px rgba(0, 0, 0, .34);
        }

        .welcome-copy {
            max-width: 660px;
            margin: 0 auto;
            color: #bdc9d4;
            font-size: clamp(.92rem, 1.6vw, 1.08rem);
            line-height: 1.9;
        }

        .welcome-meta {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: .7rem;
            margin-top: 1.45rem;
        }

        .welcome-meta span {
            padding: .42rem .72rem;
            border-radius: 8px;
            background: rgba(235, 196, 119, .09);
            color: #d8bd88;
            font-size: .76rem;
        }

        div.stButton {
            max-width: 470px;
            margin: .2rem auto 0;
        }

        div.stButton > button {
            width: 100%;
            min-height: 3.75rem;
            border: 0;
            border-radius: 999px;
            background: linear-gradient(135deg, #fff8dc, #efd38d);
            color: #17202b;
            font-size: 1.05rem;
            font-weight: 800;
            box-shadow:
                0 16px 45px rgba(0, 0, 0, .3),
                0 0 30px rgba(239, 211, 141, .12);
            transition: transform .18s ease, box-shadow .18s ease;
        }

        div.stButton > button:hover {
            color: #17202b;
            border: 0;
            transform: translateY(-2px);
            box-shadow: 0 20px 52px rgba(0, 0, 0, .38);
        }

        div.stButton > button:focus {
            color: #17202b;
            border: 0;
            box-shadow: 0 0 0 4px rgba(239, 211, 141, .35);
        }

        .welcome-note {
            margin: 1.15rem 0 0;
            color: #718292;
            font-size: .75rem;
            text-align: center;
        }

        @media (max-width: 640px) {
            .block-container {
                padding-top: 2vh;
            }

            .library-scene {
                height: 300px;
                margin-top: 1rem;
            }

            .library-scene::before,
            .library-scene::after {
                width: 22%;
            }

            .friend {
                width: 62px;
                height: 87px;
            }

            .welcome-copy br {
                display: none;
            }
        }
        </style>

        <section class="welcome-shell">
            <div class="welcome-kicker">✦ THE MIDNIGHT DENTAL LIBRARY</div>
            <div class="library-scene" aria-label="夜の図書館と歯の形をした光る入口">
                <div class="window-moon"></div>
                <div class="floor-light"></div>
                <div class="tooth-gate"></div>
                <div class="library-desk"></div>
                <div class="library-friends" aria-label="歯ブラシ、教科書、歯科ミラーの仲間たち">
                    <div class="friend toothbrush-friend">
                        <span class="friend-icon">🪥</span>
                    </div>
                    <div class="friend book-friend">
                        <span class="friend-icon">📖</span>
                    </div>
                    <div class="friend mirror-friend">
                        <span class="mirror-tool"></span>
                    </div>
                </div>
            </div>
            <h1 class="welcome-title">夜の図書館へ、ようこそ。</h1>
            <p class="welcome-copy">
                光る歯の扉の先には、第97回〜119回の知識が眠っています。<br>
                歯科の仲間たちと一緒に、今日の一問を探しにいきましょう。
            </p>
            <div class="welcome-meta">
                <span>8,000問以上を収録</span>
                <span>AND検索対応</span>
                <span>画像付きPDF出力</span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if st.button("学習をはじめる  →", type="primary"):
        st.session_state["welcome_entered"] = True
        st.rerun()

    st.markdown(
        '<p class="welcome-note">Dental Exam Archive · Student Guidance Database</p>',
        unsafe_allow_html=True,
    )
    st.stop()

# ===== データベース画面のデザイン =====
st.markdown(
    """
    <style>
    :root {
        --dq-ink: #102820;
        --dq-green: #086b50;
        --dq-green-dark: #07513e;
        --dq-lime: #b6d86b;
        --dq-paper: #f6f7f1;
        --dq-card: #fffef8;
        --dq-line: #dfe4da;
        --dq-muted: #697770;
    }

    [data-testid="stAppViewContainer"] {
        background:
            linear-gradient(rgba(8, 107, 80, .028) 1px, transparent 1px),
            var(--dq-paper);
        background-size: 100% 64px;
    }

    [data-testid="stHeader"] {
        background: rgba(246, 247, 241, .88);
        border-bottom: 1px solid rgba(16, 40, 32, .08);
        backdrop-filter: blur(14px);
    }

    .block-container {
        max-width: 1320px;
        /* Streamlit標準ヘッダーの下から本文を始め、独自ヘッダーの欠けを防ぐ */
        padding-top: 5.75rem;
        padding-bottom: 5rem;
    }

    .dq-header {
        position: relative;
        z-index: 1;
        min-height: 4rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin: 0 0 4.2rem;
        padding: .25rem 0 1.15rem;
        border-bottom: 1px solid var(--dq-line);
    }

    .dq-brand {
        display: flex;
        align-items: center;
        gap: .85rem;
    }

    .dq-mark {
        width: 48px;
        height: 48px;
        display: grid;
        place-items: center;
        border-radius: 50%;
        background: var(--dq-green);
        color: #ffffff;
        font-family: Georgia, serif;
        font-size: 1.65rem;
        font-weight: 700;
        box-shadow: 0 9px 24px rgba(8, 107, 80, .16);
    }

    .dq-brand-name {
        color: var(--dq-ink);
        font-family: Georgia, "Yu Mincho", serif;
        font-size: 1.35rem;
        font-weight: 700;
        line-height: 1.1;
    }

    .dq-brand-sub {
        margin-top: .3rem;
        color: var(--dq-muted);
        font-size: .72rem;
        letter-spacing: .07em;
    }

    .dq-edition {
        display: flex;
        align-items: center;
        gap: .55rem;
        color: var(--dq-muted);
        font-size: .82rem;
        font-weight: 700;
    }

    .dq-edition::before {
        content: "";
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: var(--dq-lime);
        box-shadow: 0 0 0 5px rgba(182, 216, 107, .18);
    }

    .dq-eyebrow {
        margin: .1rem 0 1.4rem;
        color: var(--dq-green);
        font-size: .72rem;
        font-weight: 800;
        letter-spacing: .18em;
    }

    .dq-title {
        max-width: 620px;
        margin: 0;
        color: var(--dq-ink);
        font-family: "Hiragino Mincho ProN", "Yu Mincho", Georgia, serif;
        font-size: clamp(3rem, 5.4vw, 5.2rem);
        font-weight: 500;
        line-height: 1.28;
        letter-spacing: -.055em;
    }

    .dq-lead {
        max-width: 590px;
        margin: 2rem 0 0;
        color: var(--dq-muted);
        font-family: "Hiragino Mincho ProN", "Yu Mincho", serif;
        font-size: 1rem;
        line-height: 2;
    }

    .dq-stats {
        display: flex;
        gap: clamp(1.5rem, 4vw, 3.6rem);
        max-width: 610px;
        margin-top: 2.2rem;
        padding-top: 1.35rem;
        border-top: 1px solid var(--dq-line);
    }

    .dq-stat strong {
        display: block;
        color: var(--dq-ink);
        font-family: Georgia, serif;
        font-size: 1.75rem;
        line-height: 1;
    }

    .dq-stat span {
        display: block;
        margin-top: .45rem;
        color: var(--dq-muted);
        font-size: .7rem;
        letter-spacing: .06em;
    }

    .dq-search-heading {
        margin: 0 0 .2rem;
        color: var(--dq-ink);
        font-family: "Hiragino Mincho ProN", "Yu Mincho", serif;
        font-size: 1.4rem;
        font-weight: 700;
    }

    .dq-search-copy {
        margin: 0 0 1.35rem;
        color: var(--dq-muted);
        font-size: .78rem;
        line-height: 1.7;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: rgba(16, 40, 32, .10) !important;
        border-radius: 0 !important;
        background: var(--dq-card);
        box-shadow: 0 25px 65px rgba(23, 48, 39, .09);
    }

    [data-testid="stVerticalBlockBorderWrapper"] > div {
        border-top: 5px solid var(--dq-lime);
        padding: clamp(1.4rem, 3vw, 2.2rem);
    }

    [data-testid="stTextInput"] label,
    [data-testid="stSelectbox"] label {
        color: var(--dq-ink);
        font-size: .78rem;
        font-weight: 800;
        letter-spacing: .04em;
    }

    [data-testid="stTextInput"] input {
        border: 0;
        border-bottom: 2px solid var(--dq-ink);
        border-radius: 0;
        background: transparent;
        color: var(--dq-ink);
        font-size: 1.05rem;
        box-shadow: none;
    }

    [data-testid="stTextInput"] input:focus {
        border-color: var(--dq-green);
        box-shadow: none;
    }

    [data-testid="stSelectbox"] > div > div {
        border-color: var(--dq-line);
        border-radius: 0;
        background: var(--dq-paper);
    }

    [data-testid="stAlert"] {
        border: 1px solid var(--dq-line);
        border-left: 5px solid var(--dq-green);
        border-radius: 0;
        background: var(--dq-card);
        color: var(--dq-ink);
    }

    [data-testid="stExpander"] {
        margin-bottom: .7rem;
        border: 1px solid rgba(16, 40, 32, .10);
        border-radius: 0;
        background: var(--dq-card);
        box-shadow: 0 8px 24px rgba(23, 48, 39, .035);
    }

    [data-testid="stExpander"] summary {
        color: var(--dq-ink);
        font-family: "Hiragino Mincho ProN", "Yu Mincho", serif;
        font-weight: 700;
    }

    [data-testid="stDownloadButton"] button,
    .stButton button {
        min-height: 2.8rem;
        border: 1px solid var(--dq-green);
        border-radius: 0;
        background: var(--dq-green);
        color: #ffffff;
        font-weight: 700;
    }

    [data-testid="stDownloadButton"] button:hover,
    .stButton button:hover {
        border-color: var(--dq-green-dark);
        background: var(--dq-green-dark);
        color: #ffffff;
    }

    .dq-results-title {
        margin: 3.2rem 0 1.2rem;
        color: var(--dq-ink);
        font-family: "Hiragino Mincho ProN", "Yu Mincho", serif;
        font-size: 1.8rem;
        font-weight: 600;
    }

    @media (max-width: 700px) {
        .block-container {
            padding-top: 5rem;
        }

        .dq-header {
            margin-bottom: 2.5rem;
        }

        .dq-edition {
            font-size: .7rem;
        }

        .dq-title {
            font-size: 2.7rem;
        }

        .dq-stats {
            gap: 1.4rem;
            margin-bottom: 1.7rem;
        }

        .dq-stat strong {
            font-size: 1.4rem;
        }
    }
    </style>

    <header class="dq-header">
        <div class="dq-brand">
            <div class="dq-mark">D</div>
            <div>
                <div class="dq-brand-name">Dental Query</div>
                <div class="dq-brand-sub">国家試験データベース</div>
            </div>
        </div>
        <div class="dq-edition">第97–119回</div>
    </header>
    """,
    unsafe_allow_html=True,
)

# ===== 列名正規化 & 安全取得ユーティリティ =====
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """BOM/空白/改行を除去し、よくある別名を正式名へ寄せる"""
    def _clean(s):
        s = str(s).replace("\ufeff", "")
        return re.sub(r"[\u3000 \t\r\n]+", "", s)
    df = df.copy()
    df.columns = [_clean(c) for c in df.columns]

    alias = {
        "問題文":  ["設問", "問題", "本文"],
        "選択肢1": ["選択è¢Ａ","選択肢a","A","ａ"],
        "選択è¢2": ["選択肢Ｂ","選択肢b","B","ｂ"],
        "選択肢3": ["選択肢Ｃ","選択肢c","C","ｃ"],
        "選択肢4": ["選択肢Ｄ","選択肢d","D","ｄ"],
        "選択肢5": ["選択肢Ｅ","選択肢e","E","ｅ"],
        "正解":    ["解答","答え","ans","answer"],
        "科目分類": ["分類","科目","カテゴリ","カテゴリー"],
        "リンクURL": ["画像URL","画像リンク","リンク","画像Link"],
    }
    colset = set(df.columns)
    for canon, cands in alias.items():
        if canon in colset:
            continue
        for c in cands:
            if c in colset:
                df.rename(columns={c: canon}, inplace=True)
                colset.add(canon)
                break
    return df

def safe_get(row: pd.Series | dict, keys, default=""):
    """Series/辞書から安全に値を取得（NaN, 空白, 別名を考慮）"""
    if isinstance(row, pd.Series):
        row = row.to_dict()
    for k in keys:
        if k in row:
            v = row.get(k)
            try:
                if pd.isna(v):
                    continue
            except Exception:
                pass
            s = str(v).strip() if v is not None else ""
            if s:
                return s
    return default

def ensure_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    need = ["問題文","選択肢1","選択肢2","選択肢3","選択肢4","選択肢5","正解","科目分類","リンクURL"]
    out = df.copy()
    for c in need:
        if c not in out.columns:
            out[c] = ""
    return out

# ===== データ読み込み =====
# BOM 対策のため utf-8-sig、文字列で統一して取り込み
df = pd.read_csv("97_119DB.csv", dtype=str, encoding="utf-8-sig")
df = df.fillna("")
df = normalize_columns(df)

# ===== ヒーロー・検索 =====
category_values = sorted(
    [value for value in df["科目分類"].dropna().unique().tolist() if str(value).strip()]
)

hero_col, search_col = st.columns([1.08, .92], gap="large", vertical_alignment="center")

with hero_col:
    st.markdown(
        f"""
        <div class="dq-eyebrow">DENTAL NATIONAL EXAM ARCHIVE</div>
        <h1 class="dq-title">知りたい問題へ、<br>すばやく辿り着く。</h1>
        <p class="dq-lead">
            歯科医師国家試験8,000問以上を、問題文・選択肢・分類から横断検索。
            学生指導と日々の復習のための、軽快な検索ツールです。
        </p>
        <div class="dq-stats">
            <div class="dq-stat">
                <strong>{len(df):,}</strong>
                <span>収録問題</span>
            </div>
            <div class="dq-stat">
                <strong>{len(category_values)}</strong>
                <span>分類</span>
            </div>
            <div class="dq-stat">
                <strong>23</strong>
                <span>試験回</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with search_col:
    with st.container(border=True):
        st.markdown(
            """
            <div class="dq-search-heading">キーワード検索</div>
            <p class="dq-search-copy">
                問題文・選択肢・分類・画像リンクを横断して探します。
            </p>
            """,
            unsafe_allow_html=True,
        )
        query = st.text_input(
            "検索語",
            placeholder="例：レジン & 硬さ",
            help="複数語を & でつなぐとAND検索になります。",
        )
        selected_category = st.selectbox(
            "科目分類",
            ["すべて"] + category_values,
        )
        st.caption("複数語は `&` でAND検索できます。URLの一部も検索対象です。")

if not query and selected_category == "すべて":
    st.stop()

keywords = [kw.strip() for kw in query.split("&") if kw.strip()]

def row_text(r: pd.Series) -> str:
    # 🔸 ここを変更：リンク系カラムも検索対象に含める
    parts = [
        safe_get(r, ["問題文","設問","問題","本文"]),
        *[safe_get(r, [f"選択肢{i}"]) for i in range(1,6)],
        safe_get(r, ["正解","解答","答え"]),
        safe_get(r, ["科目分類","分類","科目"]),
        # 追加：URL/画像リンク
        safe_get(r, ["リンクURL","画像URL","画像リンク","リンク","画像Link"]),
    ]
    return " ".join([p for p in parts if p])

df_filtered = df[df.apply(
    lambda row: all(kw.lower() in row_text(row).lower() for kw in keywords),
    axis=1
)]

if selected_category != "すべて":
    df_filtered = df_filtered[df_filtered["科目分類"] == selected_category]

df_filtered = df_filtered.reset_index(drop=True)

st.info(f"{len(df_filtered)}件ヒットしました")

timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
search_name = query if query else selected_category
file_prefix = f"{search_name}{timestamp}"

# ===== CSV ダウンロード =====
csv_buffer = io.StringIO()
ensure_output_columns(df_filtered).to_csv(csv_buffer, index=False)
st.download_button(
    label="📥 ヒット結果をCSVダウンロード",
    data=csv_buffer.getvalue(),
    file_name=f"{file_prefix}.csv",
    mime="text/csv"
)

# --------------------------------------------------------------------
# ▼▼▼ ここから追加（最小変更）：GoodNotes用CSVユーティリティ＋ボタン ▼▼▼

def _gn_clean(s: str) -> str:
    if s is None:
        return ""
    return str(s).replace("\ufeff", "").strip().replace("　", "")

def _gn_normalize_newlines(text: str, newline: str = "\n") -> str:
    """セル内の改行をLFに統一（必要なら CRLF へ再変換）"""
    if text is None:
        return ""
    t = re.sub(r"\r\n|\r", "\n", str(text))
    if newline == "\r\n":
        t = t.replace("\n", "\r\n")
    return t

def _gn_make_front_back(row: pd.Series,
                        numbering: str = "ABC",
                        add_labels: bool = True,
                        add_meta: bool = False) -> tuple[str, str]:
    q = _gn_clean(row.get("問題文", ""))

    choices = [
        _gn_clean(row.get("選択肢1", "")),
        _gn_clean(row.get("選択肢2", "")),
        _gn_clean(row.get("選択肢3", "")),
        _gn_clean(row.get("選択肢4", "")),
        _gn_clean(row.get("選択肢5", "")),
    ]
    labels = ["A","B","C","D","E"] if numbering == "ABC" else ["1","2","3","4","5"]
    choice_lines = [f"{labels[i]}. {_gn_normalize_newlines(txt)}" for i, txt in enumerate(choices) if txt]

    front = _gn_normalize_newlines(q)
    if choice_lines:
        front = front + "\n\n" + "\n".join(choice_lines)

    ans = _gn_clean(row.get("正解", ""))
    back = f"正解: {ans}" if add_labels else ans

    if add_meta:
        subject = _gn_clean(row.get("科目分類",""))
        link = _gn_clean(row.get("リンクURL",""))
        extra = "\n".join([s for s in (subject, link) if s])
        if extra:
            back = back + "\n\n" + _gn_normalize_newlines(extra)

    back = _gn_normalize_newlines(back)
    return front, back

def dataframe_to_goodnotes_bytes(df: pd.DataFrame,
                                 numbering: str = "ABC",
                                 add_labels: bool = True,
                                 add_meta: bool = False,
                                 overall_line_ending: str = "lf",
                                 quote_all: bool = False) -> bytes:
    """
    任意の DataFrame から GoodNotes 用 Front/Back CSV を UTF-8(BOM付き) bytes で返す。
    - セル内部の改行は LF に正規化（GoodNotesでの表示安定のため）
    - ファイル全体の改行は overall_line_ending で 'lf' or 'crlf'
    """
    # 必要列の担保（なければ空列を足す）
    base = ensure_output_columns(df)

    fronts, backs = [], []
    for _, row in base.iterrows():
        f, b = _gn_make_front_back(row, numbering=numbering, add_labels=add_labels, add_meta=add_meta)
        fronts.append(f); backs.append(b)

    out = pd.DataFrame({"Front": fronts, "Back": backs})

    # セル内部の改行をLFへ統一
    for c in out.columns:
        out[c] = out[c].map(lambda v: _gn_normalize_newlines(v, "\n"))

    # ファイルの行末
    file_nl = "\n" if overall_line_ending.lower() == "lf" else "\r\n"
    import csv as _csv  # 既存import汚染を避けるためローカル参照

    # pandasのStringIOではencoding引数が無視されるため、手動でBOMを書き込む
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM
    out.to_csv(
        buf,
        index=False,
        lineterminator=file_nl,
        quoting=_csv.QUOTE_ALL if quote_all else _csv.QUOTE_MINIMAL,
        doublequote=True,
        escapechar="\\",
    )
    return buf.getvalue().encode("utf-8")

# ▼ GoodNotesダウンロードボタン（既存CSVボタンの直下）
st.download_button(
    label="📥 GoodNotes用CSV（Front/Back）をダウンロード",
    data=dataframe_to_goodnotes_bytes(
        df_filtered,          # 検索結果をそのままFront/Back化
        numbering="ABC",      # "123"にしたい場合はここを変更
        add_labels=True,      # Back先頭に「正解: 」を付ける
        add_meta=False,       # Back末尾に 科目分類/リンクURL を追記するなら True
        overall_line_ending="lf",  # GoodNotesならLF推奨（Windows運用なら"crlf"も可）
    ),
    file_name=f"{file_prefix}_goodnotes.csv",
    mime="text/csv",
)
# --------------------------------------------------------------------

# ===== TXT 整形 =====
def convert_google_drive_link(url):
    if "drive.google.com" in url and "/file/d/" in url:
        try:
            file_id = url.split("/file/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except Exception:
            return url
    return url

def wrap_text(text: str, max_width: float, font_name: str, font_size: int):
    s = "" if text is None else str(text)
    if s == "":
        return [""]
    lines, buf = [], ""
    for ch in s:
        if _text_width(buf + ch, font_size) <= max_width:
            buf += ch
        else:
            lines.append(buf)
            buf = ch
    if buf:
        lines.append(buf)
    return lines

def wrapped_lines(prefix: str, value: str, usable_width: float, font: str, size: int):
    return wrap_text(f"{prefix}{_shape_arabic(value)}", usable_width, font, size)

def format_record_to_text(row: pd.Series) -> str:
    q = safe_get(row, ["問題文","設問","問題","本文"])
    parts = [f"問題文: {q}"]
    for i in range(1, 6):
        choice = safe_get(row, [f"選択肢{i}"])
        if choice:
            parts.append(f"選択肢{i}: {choice}")
    parts.append(f"正解: {safe_get(row, ['正解','解答','答え'])}")
    parts.append(f"分類: {safe_get(row, ['科目分類','分類','科目'])}")
    link = safe_get(row, ["リンクURL","画像URL","画像リンク","リンク","画像Link"])
    if link:
        parts.append(f"画像リンク: {convert_google_drive_link(link)}（PDFに画像表示）")
    return "\n".join(parts)

# ===== TXT ダウンロード =====
txt_buffer = io.StringIO()
for _, row in df_filtered.iterrows():
    txt_buffer.write(format_record_to_text(row))
    txt_buffer.write("\n\n" + "-"*40 + "\n\n")
st.download_button(
    label="📄 ヒット結果をTEXTダウンロード",
    data=txt_buffer.getvalue(),
    file_name=f"{file_prefix}.txt",
    mime="text/plain"
)

# ===== PDF 作成（ページ先頭は必ず問題文から／画像は必ず表示）=====
def create_pdf(records, progress=None, status=None, start_time=None):
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    c.setFont(JAPANESE_FONT, 12)
    width, height = A4

    top_margin, bottom_margin = 40, 60
    left_margin, right_margin = 40, 40
    usable_width = width - left_margin - right_margin
    page_usable_h = (height - top_margin) - bottom_margin
    line_h = 18
    y = height - top_margin

    total = len(records)

    def fmt(sec):
        m = int(sec // 60); s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    def new_page():
        nonlocal y
        c.showPage()
        c.setFont(JAPANESE_FONT, 12)
        y = height - top_margin

    def draw_wrapped_lines(lines):
        nonlocal y
        for ln in lines:
            x = left_margin
            for font, chunk in _split_font_runs(ln):
                if not chunk:
                    continue
                c.setFont(font, 12)
                c.drawString(x, y, chunk)
                x += stringWidth(chunk, font, 12)
            c.setFont(JAPANESE_FONT, 12)
            y -= line_h

    for idx, (_, row) in enumerate(records.iterrows(), start=1):
        q = safe_get(row, ["問題文","設問","問題","本文"])

        # 選択肢
        choices = []
        for i in range(1, 6):
            v = safe_get(row, [f"選択肢{i}"])
            if v:
                choices.append((i, v))

        ans = safe_get(row, ["正解","解答","答え"])
        cat = safe_get(row, ["科目分類","分類","科目"])

        # 画像の事前取得
        pil = None
        img_est_h = 0
        link_raw = safe_get(row, ["リンクURL","画像URL","画像リンク","リンク"])
        if link_raw:
            try:
                image_url = convert_google_drive_link(link_raw)
                resp = requests.get(image_url, timeout=5)
                pil = Image.open(io.BytesIO(resp.content)).convert("RGB")
                iw, ih = pil.size
                scale = min(usable_width / iw, page_usable_h / ih, 1.0)
                nw, nh = iw * scale, ih * scale
                img_est_h = nh + 20
            except Exception:
                pil = None
                img_est_h = wrapped_lines("", "[画像読み込み失敗]", usable_width, JAPANESE_FONT, 12)
                img_est_h = len(img_est_h) * line_h

        # 高さ見積り
        est_h = 0
        q_lines = wrapped_lines("問題文: ", q, usable_width, JAPANESE_FONT, 12)
        est_h += len(q_lines) * line_h
        choice_lines_list = []
        for i, v in choices:
            ls = wrapped_lines(f"選択肢{i}: ", v, usable_width, JAPANESE_FONT, 12)
            choice_lines_list.append(ls)
            est_h += len(ls) * line_h
        est_h += img_est_h if img_est_h else 0
        ans_lines = wrapped_lines("正解: ", ans, usable_width, JAPANESE_FONT, 12)
        cat_lines = wrapped_lines("分類: ", cat, usable_width, JAPANESE_FONT, 12)
        est_h += len(ans_lines) * line_h + len(cat_lines) * line_h + 20

        # ページ先頭を必ず問題文から
        if y - est_h < bottom_margin:
            new_page()

        # 描画
        draw_wrapped_lines(q_lines)
        for ls in choice_lines_list:
            draw_wrapped_lines(ls)

        if pil is not None:
            try:
                iw, ih = pil.size
                scale = min(usable_width / iw, page_usable_h / ih, 1.0)
                nw, nh = iw * scale, ih * scale
                if y - nh < bottom_margin:
                    new_page()
                remaining = y - bottom_margin
                if nh > remaining:
                    adj = remaining / nh
                    nw, nh = nw * adj, nh * adj
                img_io = io.BytesIO()
                pil.save(img_io, format="PNG")
                img_io.seek(0)
                img_reader = ImageReader(img_io)
                c.drawImage(img_reader, left_margin, y - nh, width=nw, height=nh, preserveAspectRatio=True, mask='auto')
                y -= nh + 20
            except Exception as e:
                err_lines = wrapped_lines("", f"[画像読み込み失敗: {e}]", usable_width, JAPANESE_FONT, 12)
                draw_wrapped_lines(err_lines)
        else:
            if link_raw:
                draw_wrapped_lines(wrapped_lines("", "[画像読みè¾¼み失敗]", usable_width, JAPANESE_FONT, 12))

        draw_wrapped_lines(ans_lines)
        draw_wrapped_lines(cat_lines)

        if y - 20 < bottom_margin:
            new_page()
        else:
            y -= 20

        if st.session_state.get("progress_on"):
            st.session_state["progress"].progress(min(idx / max(total, 1), 1.0))

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

# ===== PDF 生成 =====
if "pdf_bytes" not in st.session_state:
    st.session_state["pdf_bytes"] = None

if st.button("🖨️ PDFを作成（画像付き）"):
    st.session_state["progress_on"] = True
    st.session_state["progress"] = st.progress(0.0)
    start = time.time()
    with st.spinner("PDFを作成中…"):
        st.session_state["pdf_bytes"] = create_pdf(df_filtered)
    st.session_state["progress_on"] = False
    st.success("✅ PDF作成完了！")

if st.session_state["pdf_bytes"] is not None:
    st.download_button(
        label="📄 ヒット結果をPDFダウンロード",
        data=st.session_state["pdf_bytes"],
        file_name=f"{file_prefix}.pdf",
        mime="application/pdf"
    )

# ===== 画面の一覧（正解は初期非表示）=====
st.markdown(
    '<div class="dq-results-title">ヒットした問題一覧</div>',
    unsafe_allow_html=True,
)
for i, (_, record) in enumerate(df_filtered.iterrows()):
    title = safe_get(record, ["問題文","設問","問題","本文"])
    with st.expander(f"{i+1}. {title[:50]}..."):
        st.markdown("### 📝 問題文")
        st.write(title)

        st.markdown("### ✏️ 選択肢")
        for j in range(1, 6):
            val = safe_get(record, [f"選択肢{j}"])
            if val:
                st.write(f"- {val}")

        show_ans = st.checkbox("正解を表示する", key=f"show_answer_{i}", value=False)
        if show_ans:
            st.markdown(f"**✅ 正解:** {safe_get(record, ['正解','解答','答え'])}")
        else:
            st.markdown("**✅ 正解:** |||（クリックで表示）|||")

        st.markdown(f"**📚 分類:** {safe_get(record, ['科目分類','分類','科目'])}")

        link = safe_get(record, ["リンクURL","画像URL","画像リンク","リンク"])
        if link:
            st.markdown(f"[画像リンクはこちら]({convert_google_drive_link(link)})")
        else:
            st.write("（画像リンクはありません）")

# デバッグ補助（必要時だけ展開）
#with st.expander("🔧 現在の列名（正規化後）"):
#   st.write(list(df.columns))

