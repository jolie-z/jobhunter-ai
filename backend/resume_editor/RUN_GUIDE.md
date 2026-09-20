# 多平台在线简历编辑器 - 运行指南

## 🚀 快速开始

### 步骤1：采集所有平台字段数据

打开终端，依次运行以下命令：

```bash
# 进入项目目录
cd <repo-root>/backend

# 1. 采集BOSS直聘（已完成）
python3 resume_editor/platforms/boss_editor.py

# 2. 采集猎聘（已完成）
python3 resume_editor/platforms/liepin_editor.py

# 3. 采集51job
python3 resume_editor/platforms/job51_editor.py

# 4. 采集智联招聘
python3 resume_editor/platforms/zhilian_editor.py
```

### 步骤2：启动后端服务

```bash
# 进入后端目录
cd <repo-root>/backend

# 启动FastAPI服务
uvicorn app.main:app --reload --port 8000
```

### 步骤3：启动前端服务

```bash
# 进入前端目录（新开一个终端）
cd <repo-root>/frontend

# 启动Next.js开发服务器
npm run dev
```

### 步骤4：访问简历编辑器

打开浏览器，访问：
```
http://localhost:3000/resume-editor
```

---

## 📊 预期结果

### 采集完成后

你应该看到类似以下的输出：

```
============================================================
🔍 51job在线简历字段采集器
============================================================

🔄 正在导航到51job简历页面...

📋 1. 正在解析基本信息...
  ✅ 基本信息：采集到 7 个字段

📋 2. 正在解析求职期望...
  ✅ 求职期望：采集到 3 个字段

...

✅ 字段已保存到: <repo-root>/backend/resume_editor/data/51job_fields.json

============================================================
📊 采集统计
============================================================
✅ 总字段数: 15
✅ 必填字段: 6 (顶级) + 9 (数组子字段)
✅ 选填字段: 9
============================================================
```

### 前端页面功能

访问 `http://localhost:3000/resume-editor` 后，你应该看到：

1. **平台选择**：4个平台的复选框
2. **操作按钮**：刷新数据、导出、同步
3. **字段展示**：各平台的简历字段
4. **编辑功能**：可以编辑各字段（待完善）

---

## 🔧 故障排查

### 问题1：采集脚本报错

**错误信息**：`ModuleNotFoundError: No module named 'xxx'`

**解决方案**：
```bash
# 确保在正确的目录下运行
cd <repo-root>/backend

# 确保Python路径正确
export PYTHONPATH="${PYTHONPATH}:<repo-root>/backend"
```

### 问题2：浏览器未启动

**错误信息**：`浏览器连接失败`

**解决方案**：
1. 确保已安装 Microsoft Edge 浏览器
2. 确保浏览器可以正常启动
3. 检查是否有其他浏览器实例占用端口

### 问题3：前端页面无法访问

**错误信息**：`无法访问此网站`

**解决方案**：
1. 确保后端服务已启动（端口8000）
2. 确保前端服务已启动（端口3000）
3. 检查防火墙设置

### 问题4：API接口报错

**错误信息**：`404 Not Found`

**解决方案**：
1. 确保已注册API路由
2. 检查路由前缀是否正确
3. 重启后端服务

---

## 📝 采集脚本说明

### BOSS直聘采集器
- **文件**：`resume_editor/platforms/boss_editor.py`
- **数据文件**：`resume_editor/data/boss_fields.json`
- **状态**：✅ 已完成

### 猎聘网采集器
- **文件**：`resume_editor/platforms/liepin_editor.py`
- **数据文件**：`resume_editor/data/liepin_fields.json`
- **状态**：✅ 已完成

### 51job采集器
- **文件**：`resume_editor/platforms/job51_editor.py`
- **数据文件**：`resume_editor/data/51job_fields.json`
- **状态**：⏳ 待运行

### 智联招聘采集器
- **文件**：`resume_editor/platforms/zhilian_editor.py`
- **数据文件**：`resume_editor/data/zhilian_fields.json`
- **状态**：⏳ 待运行

---

## 🎯 采集字段说明

### 通用字段（所有平台都有）
- 姓名
- 手机号
- 邮箱
- 求职状态
- 最高学历
- 工作年限

### 求职期望字段
- 期望职位
- 期望城市
- 期望薪资

### 经历字段
- 工作经历（公司、职位、时间、描述）
- 教育经历（学校、专业、学历、时间）
- 项目经历（项目名、角色、时间、描述）

### 其他字段
- 技能标签
- 资格证书
- 自我评价/个人优势

---

## 💡 使用技巧

### 1. 批量采集
可以编写一个脚本批量运行所有采集器：

```bash
#!/bin/bash
cd <repo-root>/backend

echo "开始采集BOSS直聘..."
python3 resume_editor/platforms/boss_editor.py

echo "开始采集猎聘..."
python3 resume_editor/platforms/liepin_editor.py

echo "开始采集51job..."
python3 resume_editor/platforms/job51_editor.py

echo "开始采集智联招聘..."
python3 resume_editor/platforms/zhilian_editor.py

echo "所有平台采集完成！"
```

### 2. 定时采集
可以设置定时任务，每天自动采集：

```bash
# 编辑crontab
crontab -e

# 添加以下行（每天凌晨2点采集）
0 2 * * * cd <repo-root>/backend && python3 resume_editor/platforms/boss_editor.py
```

### 3. 数据备份
采集完成后，建议备份数据：

```bash
cd <repo-root>/backend
cp -r resume_editor/data resume_editor/data_backup_$(date +%Y%m%d)
```

---

## 📞 常见问题

### Q1：为什么采集到的数据为空？
**A1**：可能是以下原因：
- 未登录招聘平台
- 页面结构已更新
- 选择器需要调整

### Q2：如何更新采集到的数据？
**A2**：重新运行采集脚本即可，会自动覆盖旧数据。

### Q3：前端页面显示"暂无数据"？
**A3**：确保：
- 已运行采集脚本
- 后端服务已启动
- API接口正常

### Q4：如何添加新的招聘平台？
**A4**：
1. 创建新的采集器：`resume_editor/platforms/xxx_editor.py`
2. 创建新的API端点
3. 更新前端页面

---

## 📚 相关文档

- [项目总结](backend/resume_editor/FULL_SUMMARY.md)
- [进度报告](backend/resume_editor/PROGRESS_REPORT.md)
- [API文档](backend/app/api/resume_editor.py)

---

## 🎉 完成检查清单

- [ ] BOSS直聘数据已采集
- [ ] 猎聘数据已采集
- [ ] 51job数据已采集
- [ ] 智联招聘数据已采集
- [ ] 后端服务已启动
- [ ] 前端服务已启动
- [ ] 可以访问前端页面
- [ ] 可以查看各平台数据
- [ ] 字段编辑功能正常（待完善）
- [ ] 数据同步功能正常（待实现）

---

## 📞 技术支持

如有问题，请：
1. 查看本文档的故障排查部分
2. 检查控制台错误信息
3. 查看项目日志
4. 联系项目负责人

---

**最后更新**：2026-07-18
**版本**：1.0.0
**状态**：开发中
