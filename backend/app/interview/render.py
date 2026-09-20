def render_waiting_page() -> str:
    """渲染生成中的 Loading 候车室页面"""
    return """
    <!DOCTYPE html>
    <html lang="zh">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>临考锦囊正在生成中...</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", STHeiti, "Microsoft Yahei", sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background-color: #f8fafc; color: #334155; text-align: center; padding: 20px; margin: 0;}
            .loader { border: 4px solid #e2e8f0; border-top: 4px solid #3b82f6; border-radius: 50%; width: 48px; height: 48px; animation: spin 1s linear infinite; margin-bottom: 24px;}
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            h2 { margin-bottom: 10px; color: #1e293b; }
        </style>
        <script>
            setTimeout(function(){ window.location.reload(1); }, 3000);
        </script>
    </head>
    <body>
        <div class="loader"></div>
        <h2>临考锦囊正在快马加鞭生成中... 🐎</h2>
        <p>AI 正在全网搜罗情报、预测考题并进行排版，大约需要 15 秒。</p>
        <p style="color: #94a3b8; font-size: 14px;">页面会自动刷新，请不要退出...</p>
    </body>
    </html>
    """

def render_handbook_page(data: dict) -> str:
    """渲染最终的临考锦囊页面"""
    import markdown
    company_name = data.get("company_name", "目标公司")
    raw_job_group = data.get("raw_job_group", "职位")
    company_intel = data.get("company_intel", "")
    summary_text = data.get("summary_text", "")
    predicted_qa = data.get("predicted_qa", "")
    reverse_questions = data.get("reverse_questions", "")

    return f"""
    <!DOCTYPE html>
    <html lang="zh">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>{company_name} 面试锦囊</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", STHeiti, "Microsoft Yahei", sans-serif; line-height: 1.6; color: #334155; background-color: #f8fafc; margin: 0; padding: 16px; }}
            .header {{ text-align: center; border-bottom: 2px solid #3b82f6; padding-bottom: 12px; margin-bottom: 20px; }}
            h1 {{ font-size: 20px; color: #1e293b; margin: 0; }}
            .card {{ background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); overflow-wrap: break-word; }}
            h2 {{ font-size: 16px; padding-bottom: 8px; margin-top: 0; }}
            h3 {{ font-size: 14px; color: #0f172a; }}
            pre, code {{ background: #f1f5f9; padding: 4px 6px; border-radius: 6px; white-space: pre-wrap; word-break: break-all; font-size: 13px; }}
            p, li {{ font-size: 14px; color: #475569; }}
            ul {{ padding-left: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🎯 {company_name} - {raw_job_group} 临考锦囊</h1>
        </div>
        <div class="card">
            <h2>🏢 外部 API 情报：公司概况与业务洞察</h2>
            <div>{markdown.markdown(company_intel)}</div>
        </div>
        <div class="card">
            <h2>🎯 领域面经库：赛道高频考点</h2>
            <div>{markdown.markdown(summary_text)}</div>
        </div>
        <div class="card" style="background: #ecfdf5; border-color: #a7f3d0;">
            <h2 style="color: #065f46; border-bottom-color: #6ee7b7;">🔮 绝密押题：AI 考点预测</h2>
            <div>{markdown.markdown(predicted_qa)}</div>
        </div>
        <div class="card" style="background: #f5f3ff; border-color: #ddd6fe;">
            <h2 style="color: #5b21b6; border-bottom-color: #a78bfa;">💡 黄金反问环节</h2>
            <div>{markdown.markdown(reverse_questions)}</div>
        </div>
    </body>
    </html>
    """
