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
from reportlab.lib.utils import ImageReader   # ★ 追加：ReportLab用の画像ラッパー
import time

from pathlib import Path
from reportlab.pdfbase.cidfonts import UnicodeCIDFont


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

st.set_page_config(page_title="🔍 学生指導用データベース", layout="wide")
st.title("🔍 学生指導用データベース")

# ===== データ読み込み =====
df = pd.read_csv("image7559.csv")

# ===== 検索 =====
query = st.text_input("問題文・選択肢・分類で検索:")
st.caption("💡 検索語を `&` でつなげるとAND検索ができます（例: レジン & 硬さ）")

# 初期表示では何も描画しない
if not query:
    st.stop()

keywords = [kw.strip() for kw in query.split("&") if kw.strip()]
df_filtered = df[df.apply(
    lambda row: all(
        kw.lower() in row.astype(str).str.lower().str.cat(sep=" ")
        for kw in keywords
    ), axis=1
)]

st.info(f"{len(df_filtered)}件ヒットしました")

timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
safe_query = query if query else "検索なし"
file_prefix = f"{safe_query}{timestamp}"

# ===== CSV ダウンロード =====
csv_buffer = io.StringIO()
df_filtered.to_csv(csv_buffer, index=False)
st.download_button(
    label="📥 ヒット結果をCSVダウンロード",
    data=csv_buffer.getvalue(),
    file_name=f"{file_prefix}.csv",
    mime="text/csv"
)

# ===== TXT 整形 =====
def format_record_to_text(row):
    parts = [f"問題文: {row['問題文']}"]
    for i in range(1, 6):
        choice = row.get(f"選択肢{i}", "")
        if pd.notna(choice):
            parts.append(f"選択肢{i}: {choice}")
    parts.append(f"正解: {row['正解']}")
    parts.append(f"分類: {row['科目分類']}")
    if pd.notna(row.get("リンクURL", "")) and str(row["リンクURL"]).strip() != "":
        parts.append(f"画像リンク: {row['リンクURL']}（PDFに画像表示）")
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

# ===== Google Drive 直リンク化 =====
def convert_google_drive_link(url):
    if "drive.google.com" in url and "/file/d/" in url:
        try:
            file_id = url.split("/file/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except Exception:
            return url
    return url

# ===== 折り返し（PDF用）=====
def wrap_text(text: str, max_width: float, font_name: str, font_size: int):
    if text is None:
        return [""]
    s = str(text)
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

# ===== PDF 作成（画像はみ出し防止＋ImageReader使用）=====
def create_pdf(records, progress=None, status=None, start_time=None):
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    c.setFont(JAPANESE_FONT, 12)
    width, height = A4

    # 余白とレイアウト
    top_margin = 40
    bottom_margin = 60
    left_margin = 40
    right_margin = 40
    usable_width = width - left_margin - right_margin
    line_h = 18
    y = height - top_margin

    total = len(records)

    def fmt(sec):
        m = int(sec // 60); s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    def draw_wrapped(prefix, text):
        nonlocal y
        for sub in wrap_text(f"{prefix}{text}", usable_width, JAPANESE_FONT, 12):
            c.drawString(left_margin, y, sub)
            y -= line_h
            if y < bottom_margin:
                c.showPage(); c.setFont(JAPANESE_FONT, 12); y = height - top_margin

    for idx, (_, row) in enumerate(records.iterrows(), start=1):
        # ---- 問題文 ----
        draw_wrapped("問題文: ", row.get("問題文", ""))

        # ---- 選択肢 ----
        for i in range(1, 6):
            val = row.get(f"選択肢{i}", None)
            if pd.notna(val) and str(val).strip() != "":
                draw_wrapped(f"選択肢{i}: ", val)

        # ---- 画像 ----
        link_raw = row.get("リンクURL", None)
        if pd.notna(link_raw) and str(link_raw).strip() != "":
            image_url = convert_google_drive_link(str(link_raw).strip())
            try:
                response = requests.get(image_url, timeout=5)
                pil = Image.open(io.BytesIO(response.content)).convert("RGB")
                iw, ih = pil.size

                # 初期スケール（横幅＆最大高さ200ptの制約）
                max_h_limit = 200
                base_scale = min(usable_width / iw, max_h_limit / ih, 1.0)
                nw, nh = iw * base_scale, ih * base_scale

                # 残り縦スペースに入らない場合は改ページして再計算
                remaining_h = y - bottom_margin
                if nh > remaining_h:
                    c.showPage(); c.setFont(JAPANESE_FONT, 12)
                    y = height - top_margin
                    remaining_h = y - bottom_margin
                    base_scale = min(usable_width / iw, min(max_h_limit, remaining_h) / ih, 1.0)
                    nw, nh = iw * base_scale, ih * base_scale

                # それでも大きければ高さ側でさらに調整
                if nh > (y - bottom_margin):
                    adj = (y - bottom_margin) / nh
                    nw, nh = nw * adj, nh * adj

                # ReportLab が受け取れる形式にする（★ここが修正点）
                img_io = io.BytesIO()
                pil.save(img_io, format="PNG")
                img_io.seek(0)
                img_reader = ImageReader(img_io)

                # 描画（アスペクト比維持）
                c.drawImage(img_reader, left_margin, y - nh,
                            width=nw, height=nh, preserveAspectRatio=True, mask='auto')
                y -= nh + 20
                if y < bottom_margin:
                    c.showPage(); c.setFont(JAPANESE_FONT, 12); y = height - top_margin

            except Exception as e:
                draw_wrapped("", f"[画像読み込み失敗: {e}]")

        # ---- 正解・分類 ----
        draw_wrapped("正解: ", row.get("正解", ""))
        draw_wrapped("分類: ", row.get("科目分類", ""))

        # セパレータ
        y -= 20
        if y < bottom_margin:
            c.showPage(); c.setFont(JAPANESE_FONT, 12); y = height - top_margin

        # 進捗表示
        if progress is not None:
            progress.progress(min(idx / max(total, 1), 1.0))
        if status is not None and start_time is not None:
            elapsed = time.time() - start_time
            avg = elapsed / idx
            remaining = max(total - idx, 0) * avg
            status.text(f"PDF作成中… {idx}/{total}  経過 {fmt(elapsed)}  残り目安 {fmt(remaining)}")

    c.save(); pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

# ===== PDF 生成（押した時だけ）=====
if "pdf_bytes" not in st.session_state:
    st.session_state["pdf_bytes"] = None

if st.button("🖨️ PDFを作成（画像付き）"):
    progress_bar = st.progress(0.0)
    status = st.empty()
    start = time.time()
    with st.spinner("PDFを作成中…"):
        st.session_state["pdf_bytes"] = create_pdf(
            df_filtered, progress=progress_bar, status=status, start_time=start
        )
    status.text("✅ PDF作成完了！")

if st.session_state["pdf_bytes"] is not None:
    st.download_button(
        label="📄 ヒット結果をPDFダウンロード",
        data=st.session_state["pdf_bytes"],
        file_name=f"{file_prefix}.pdf",
        mime="application/pdf"
    )

# ===== 画面の一覧（画像はリンクのみ）=====
st.markdown("### 🔍 ヒットした問題一覧")
for i, (_, record) in enumerate(df_filtered.iterrows()):
    with st.expander(f"{i+1}. {record['問題文'][:50]}..."):
        st.markdown("### 📝 問題文")
        st.write(record["問題文"])
        st.markdown("### ✏️ 選択肢")
        for j in range(1, 6):
            if pd.notna(record.get(f"選択肢{j}", None)):
                st.write(f"- {record[f'選択肢{j}']}")
        st.markdown(f"**✅ 正解:** {record['正解']}")
        st.markdown(f"**📚 分類:** {record['科目分類']}")
        if pd.notna(record.get("リンクURL", None)) and str(record["リンクURL"]).strip() != "":
            image_url = convert_google_drive_link(record["リンクURL"])
            st.markdown(f"[画像リンクはこちら]({image_url})")
        else:
            st.write("（画像リンクはありません）")
