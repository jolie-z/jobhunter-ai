# vditor 自托管静态资产来源

- 来源包：`vditor@4.0.0`（与 `frontend/package.json` 中钉死的 `"vditor": "4.0.0"` 必须保持一致）
- 拷贝时间：2026-09-23
- 同步命令（升级 vditor 版本后须重新执行，缺目录会导致编辑器初始化静默失败——
  i18n 曾因漏拷 404 使 `window.VditorI18n` 未定义、init 链在 lute 之前死掉）：

```bash
cd frontend
mkdir -p public/vditor/dist/js/lute public/vditor/dist/js/icons public/vditor/dist/js/i18n public/vditor/dist/css
cp node_modules/vditor/dist/js/lute/*   public/vditor/dist/js/lute/
cp node_modules/vditor/dist/js/icons/*  public/vditor/dist/js/icons/
cp node_modules/vditor/dist/js/i18n/*   public/vditor/dist/js/i18n/
cp -R node_modules/vditor/dist/css/*    public/vditor/dist/css/
```

- 组件侧对应配置：`markdown-editor.tsx` 中 `cdn: "/vditor"`。
- 未拷贝的按需模块（hljs/katex/mermaid/echarts 等富渲染）：简历正文极少用到，
  启用时回退为无高亮纯文本，不影响编辑与保存；如需支持再按同法补拷。
