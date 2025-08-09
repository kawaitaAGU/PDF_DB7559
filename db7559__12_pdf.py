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
import time  # ← 経過時間用

# PDFフォント設定
pdfmetrics.registerFont(TTFont("Japanese", "fonts/IPAexGothic.ttf"))

st.set_page_config(page_title="🔍 学生指導用データベース", layout="wide")
st.title("🔍 学生指導用データベース")

# CSV読み込み
df = pd.read_csv("image7559.csv")

query = st.text_input("問題文・選択肢・分類で検索:")
st.caption("💡 検索語を `&` でつなげるとAND検索ができます（例: レジン & 硬さ）")

# 初期表示では停止
if not query:
    st.stop()

# 検索処理
keywords = [kw.strip() for kw in query.split("&") if kw.strip()]
df_filtered = df[df.apply(
    lambda row: all(
        kw.lower() in row.astype(str).str.lower().str.cat(sep=" ")
        for kw in keywords
    ), axis=1)]

st.info(f"{len(df_filtered)}件ヒットしました")

timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
safe_query = query if query else "検索なし"
file_prefix = f"{safe_query}{timestamp}"

# CSV ダウンロード
csv_buffer = io.StringIO()
df_filtered.to_csv(csv_buffer, index=False)
st.download_button(
    label="📥 ヒット結果をCSVダウンロード",
    data=csv_buffer.getvalue(),
    file_name=f"{file_prefix}.csv",
    mime="text/csv"
)

# TXT出力用関数
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

# TXT ダウンロード
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

# Google Driveリンク変換
def convert_google_drive_link(url):
    if "drive.google.com" in url and "/file/d/" in url:
        try:
            file_id = url.split("/file/d/")[1].split("/")[0]
            return f"https://drive.google.com/uc?export=view&id={file_id}"
        except:
            return url
    return url

# PDF作成関数（進捗付き）
def create_pdf(records, progress=None, status=None, start_time=None):
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    c.setFont("Japanese", 12)
    width, height = A4
    y = height - 40

    total = len(records)

    def fmt(sec):
        m = int(sec // 60); s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    for idx, (_, row) in enumerate(records.iterrows(), start=1):
        text = format_record_to_text(row).split("\n")
        for line in text:
            c.drawString(40, y, line)
            y -= 18
            if y < 100:
                c.showPage()
                c.setFont("Japanese", 12)
                y = height - 40

        if pd.notna(row.get("リンクURL", "")) and str(row["リンクURL"]).strip() != "":
            image_url = convert_google_drive_link(row["リンクURL"])
            try:
                response = requests.get(image_url, timeout=5)
                img = Image.open(io.BytesIO(response.content)).convert("RGB")
                img_width, img_height = img.size
                scale = min((width - 80) / img_width, 200 / img_height, 1.0)
                new_width = img_width * scale
                new_height = img_height * scale
                img_io = io.BytesIO()
                img.save(img_io, format="PNG")
                img_io.seek(0)
                c.drawInlineImage(Image.open(img_io), 40, y - new_height,
                                  width=new_width, height=new_height)
                y -= new_height + 20
                if y < 100:
                    c.showPage()
                    c.setFont("Japanese", 12)
                    y = height - 40
            except Exception as e:
                c.drawString(40, y, f"[画像読み込み失敗: {e}]")
                y -= 20

        y -= 20

        # 進捗更新
        if progress is not None:
            progress.progress(min(idx / max(total, 1), 1.0))
        if status is not None and start_time is not None:
            elapsed = time.time() - start_time
            avg = elapsed / idx
            remaining = max(total - idx, 0) * avg
            status.text(f"PDF作成中… {idx}/{total}  経過 {fmt(elapsed)}  残り目安 {fmt(remaining)}")

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()

# PDF作成ボタンと進捗表示
if "pdf_bytes" not in st.session_state:
    st.session_state["pdf_bytes"] = None

if st.button("🖨️ PDFを作成（画像付き）"):
    progress_bar = st.progress(0.0)
    status = st.empty()
    start = time.time()
    with st.spinner("PDFを作成中…"):
        st.session_state["pdf_bytes"] = create_pdf(
            df_filtered,
            progress=progress_bar,
            status=status,
            start_time=start
        )
    status.text("✅ PDF作成完了！")

if st.session_state["pdf_bytes"] is not None:
    st.download_button(
        label="📄 ヒット結果をPDFダウンロード",
        data=st.session_state["pdf_bytes"],
        file_name=f"{file_prefix}.pdf",
        mime="application/pdf"
    )

# 一覧表示（リンクのみ）
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