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

st.set_page_config(page_title="🔍 国家試験用データベース", layout="wide")
st.title("🔍 日本歯科理工学会発表用_歯科医師国家試験データベース")

# ===== 列名正規化 & 安全取得ユーティリティ =====
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """BOM/空白/改行を除去し、よくある別名を正式名へ寄せる"""
    def _clean(s):
        s = str(s).replace("\ufeff", "")
        return re.sub(r"[\u3000 \t\r\n]+", "", s)

    df = df.copy()
    df.columns = [_clean(c) for c in df.columns]

    alias = {
        "問題番号": ["問題番号ID", "ID", "設問番号", "問題ID"],
        "問題文": ["設問", "問題", "本文"],
        "選択肢1": ["選択肢Ａ", "選択肢a", "A", "ａ"],
        "選択肢2": ["選択肢Ｂ", "選択肢b", "B", "ｂ"],
        "選択肢3": ["選択肢Ｃ", "選択肢c", "C", "ｃ"],
        "選択肢4": ["選択肢Ｄ", "選択肢d", "D", "ｄ"],
        "選択肢5": ["選択肢Ｅ", "選択肢e", "E", "ｅ"],
        "正解": ["解答", "答え", "ans", "answer"],
        "科目分類": ["分類", "科目", "カテゴリ", "カテゴリー"],
        "リンクURL": ["画像URL", "画像リンク", "リンク", "画像Link"],
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


def ensure_search_columns(df: pd.DataFrame) -> pd.DataFrame:
    need = [
        "問題番号",
        "問題文",
        "選択肢1",
        "選択肢2",
        "選択肢3",
        "選択肢4",
        "選択肢5",
        "正解",
        "科目分類",
        "リンクURL",
    ]
    out = df.copy()
    for c in need:
        if c not in out.columns:
            out[c] = ""
    return out


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
        if stringWidth(buf + ch, font_name, font_size) <= max_width:
            buf += ch
        else:
            lines.append(buf)
            buf = ch
    if buf:
        lines.append(buf)
    return lines


def wrapped_lines(prefix: str, value: str, usable_width: float, font: str, size: int):
    return wrap_text(f"{prefix}{value}", usable_width, font, size)


def format_record_to_text(row: pd.Series) -> str:
    no = safe_get(row, ["問題番号", "問題番号ID", "ID", "設問番号"])
    q = safe_get(row, ["問題文", "設問", "問題", "本文"])

    parts = []
    if no:
        parts.append(f"問題番号: {no}")
    parts.append(f"問題文: {q}")

    for i in range(1, 6):
        choice = safe_get(row, [f"選択肢{i}"])
        if choice:
            parts.append(f"選択肢{i}: {choice}")

    parts.append(f"正解: {safe_get(row, ['正解', '解答', '答え'])}")
    parts.append(f"分類: {safe_get(row, ['科目分類', '分類', '科目'])}")

    link = safe_get(row, ["リンクURL", "画像URL", "画像リンク", "リンク", "画像Link"])
    if link:
        parts.append(f"画像リンク: {convert_google_drive_link(link)}（PDFに画像表示）")

    return "\n".join(parts)


# ===== データ読み込み =====
@st.cache_data(show_spinner=False)
def load_data():
    df = pd.read_csv("97_118DB.csv", dtype=str, encoding="utf-8-sig")
    df = df.fillna("")
    df = normalize_columns(df)
    df = ensure_search_columns(df)

    search_cols = [
        "問題番号",
        "問題文",
        "選択肢1",
        "選択肢2",
        "選択肢3",
        "選択肢4",
        "選択肢5",
        "正解",
        "科目分類",
        "リンクURL",
    ]

    df["_search_text"] = (
        df[search_cols]
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )

    return df

df = load_data()

# ===== 検索 =====
query = st.text_input("問題番号・問題文・選択肢・分類・画像リンク(URL)で検索:")
st.caption("💡 検索語を `&` でつなげるとAND検索（例: 理工 & 118、レジン & 硬さ）。URLの一部（例: http, drive.google）でも可。")

if not query:
    st.stop()

keywords = [kw.strip().lower() for kw in query.split("&") if kw.strip()]

mask = pd.Series(True, index=df.index)
for kw in keywords:
    mask &= df["_search_text"].str.contains(kw, regex=False, na=False)

df_filtered = df.loc[mask].reset_index(drop=True)

st.info(f"{len(df_filtered)}件ヒットしました")

timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
file_prefix = f"{(query if query else '検索なし')}{timestamp}"

# ===== TXT ダウンロード =====
txt_buffer = io.StringIO()
for _, row in df_filtered.iterrows():
    txt_buffer.write(format_record_to_text(row))
    txt_buffer.write("\n\n" + "-" * 40 + "\n\n")

st.download_button(
    label="📄 ヒット結果をTEXTダウンロード",
    data=txt_buffer.getvalue(),
    file_name=f"{file_prefix}.txt",
    mime="text/plain"
)

# ===== PDF 作成（ページ先頭は必ず問題文から／画像は必ず表示）=====
def create_pdf(records):
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

    def new_page():
        nonlocal y
        c.showPage()
        c.setFont(JAPANESE_FONT, 12)
        y = height - top_margin

    def draw_wrapped_lines(lines):
        nonlocal y
        for ln in lines:
            c.drawString(left_margin, y, ln)
            y -= line_h

    for idx, (_, row) in enumerate(records.iterrows(), start=1):
        no = safe_get(row, ["問題番号", "問題番号ID", "ID", "設問番号"])
        q = safe_get(row, ["問題文", "設問", "問題", "本文"])

        choices = []
        for i in range(1, 6):
            v = safe_get(row, [f"選択肢{i}"])
            if v:
                choices.append((i, v))

        ans = safe_get(row, ["正解", "解答", "答え"])
        cat = safe_get(row, ["科目分類", "分類", "科目"])

        pil = None
        img_est_h = 0
        link_raw = safe_get(row, ["リンクURL", "画像URL", "画像リンク", "リンク", "画像Link"])
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
                fail_lines = wrapped_lines("", "[画像読み込み失敗]", usable_width, JAPANESE_FONT, 12)
                img_est_h = len(fail_lines) * line_h

        est_h = 0

        no_lines = []
        if no:
            no_lines = wrapped_lines("問題番号: ", no, usable_width, JAPANESE_FONT, 12)
            est_h += len(no_lines) * line_h

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

        if y - est_h < bottom_margin:
            new_page()

        if no_lines:
            draw_wrapped_lines(no_lines)

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
                c.drawImage(
                    img_reader,
                    left_margin,
                    y - nh,
                    width=nw,
                    height=nh,
                    preserveAspectRatio=True,
                    mask='auto'
                )
                y -= nh + 20
            except Exception as e:
                err_lines = wrapped_lines("", f"[画像読み込み失敗: {e}]", usable_width, JAPANESE_FONT, 12)
                draw_wrapped_lines(err_lines)
        else:
            if link_raw:
                draw_wrapped_lines(wrapped_lines("", "[画像読み込み失敗]", usable_width, JAPANESE_FONT, 12))

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
st.markdown("### 🔍 ヒットした問題一覧")
for i, (_, record) in enumerate(df_filtered.iterrows()):
    no = safe_get(record, ["問題番号", "問題番号ID", "ID", "設問番号"])
    title = safe_get(record, ["問題文", "設問", "問題", "本文"])

    head = f"{i+1}. "
    if no:
        head += f"[{no}] "
    head += f"{title[:50]}..."

    with st.expander(head):
        if no:
            st.markdown(f"**🆔 問題番号:** {no}")

        st.markdown("### 📝 問題文")
        st.write(title)

        st.markdown("### ✏️ 選択肢")
        for j in range(1, 6):
            val = safe_get(record, [f"選択肢{j}"])
            if val:
                st.write(f"- {val}")

        show_ans = st.checkbox("正解を表示する", key=f"show_answer_{i}", value=False)
        if show_ans:
            st.markdown(f"**✅ 正解:** {safe_get(record, ['正解', '解答', '答え'])}")
        else:
            st.markdown("**✅ 正解:** |||（クリックで表示）|||")

        st.markdown(f"**📚 分類:** {safe_get(record, ['科目分類', '分類', '科目'])}")

        link = safe_get(record, ["リンクURL", "画像URL", "画像リンク", "リンク", "画像Link"])
        if link:
            st.markdown(f"[画像リンクはこちら]({convert_google_drive_link(link)})")
        else:
            st.write("（画像リンクはありません）")
