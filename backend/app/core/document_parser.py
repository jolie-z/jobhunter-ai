"""
统一文档解析层：PDF/DOCX → Markdown 文本。

策略：优先使用 markitdown（对表格、复杂排版、标题层级解析更好），
失败时降级到 fitz / python-docx（项目原有的纯文本抽取）。

注意：markitdown、fitz、python-docx 都是同步阻塞库，必须用 asyncio.to_thread
包装，避免阻塞 FastAPI 的事件循环。
"""

import asyncio
import io
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("document_parser")


async def parse_document_to_markdown(file_bytes: bytes, filename: str) -> str:
    """将上传的文件转为 Markdown 文本。

    优先 markitdown；markitdown 抛异常或返回空文本时，降级到 fitz/python-docx。

    Args:
        file_bytes: 原始文件字节
        filename: 原始文件名（用于扩展名判断）

    Returns:
        Markdown / 纯文本字符串

    Raises:
        ValueError: 两种方式都解析失败时
    """
    try:
        text = await asyncio.to_thread(_markitdown_convert, file_bytes, filename)
        if text.strip():
            return text
        logger.warning("markitdown 返回空文本，降级到 fitz/python-docx")
    except Exception as e:
        logger.warning(f"markitdown 解析失败({e})，降级到 fitz/python-docx")

    # 降级路径
    return await asyncio.to_thread(_legacy_convert, file_bytes, filename)


def _markitdown_convert(file_bytes: bytes, filename: str) -> str:
    """使用 markitdown 转换。"""
    from markitdown import MarkItDown

    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    try:
        result = MarkItDown().convert(str(tmp_path))
        return result.text_content or ""
    finally:
        tmp_path.unlink(missing_ok=True)


def _legacy_convert(file_bytes: bytes, filename: str) -> str:
    """fitz / python-docx 纯文本抽取，作为降级兜底（来自原 router.py:139-146）。"""
    import fitz
    from docx import Document

    raw_text = ""
    if filename.lower().endswith(".pdf"):
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            raw_text += page.get_text() + "\n"
    elif filename.lower().endswith(".docx"):
        doc = Document(io.BytesIO(file_bytes))
        for para in doc.paragraphs:
            raw_text += para.text + "\n"
    else:
        raise ValueError("仅支持 PDF 或 DOCX 格式")

    if not raw_text.strip():
        raise ValueError("文档解析未提取到任何文本（可能是扫描件 PDF，需 OCR）")
    return raw_text
