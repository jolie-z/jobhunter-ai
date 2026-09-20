# BOSS直聘页面检查 - 运行指南

## 🚀 快速开始

### 方法1：检查页面结构（推荐）

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/check_boss_page.py
```

这个脚本会：
1. 访问BOSS直聘简历页面
2. 检查页面结构
3. 搜索关键词
4. 保存HTML文件

---

### 方法2：运行完整爬虫（带选择）

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/boss_job_list_scraper.py 3
```

参数说明：
- `1`：方法1 - 查找输入框并点击
- `2`：方法2 - 尝试不同选择器
- `3`：方法3 - 检查页面结构
- `4`：方法4 - 手动交互
- `5`：运行所有方法

---

## 📊 查看结果

### 查看保存的HTML文件

```bash
cat backend/resume_editor/data/boss_page_structure.html
```

### 搜索关键词

```bash
# 搜索职位分类
grep "技术\|产品\|设计" backend/resume_editor/data/boss_page_structure.html

# 搜索具体的职位
grep "后端开发\|前端开发\|Java\|Python" backend/resume_editor/data/boss_page_structure.html

# 搜索期望职位相关
grep "期望职位\|选择期望职位" backend/resume_editor/data/boss_page_structure.html
```

---

## 🎯 预期结果

### 成功情况

```
✅ '期望职位': 出现 5 次
✅ '技术': 存在
✅ '产品': 存在
✅ '设计': 存在
✅ text:期望职位: 1 个元素
✅ ka:user-resume-edit-expectation0: 1 个元素
```

### 失败情况

```
❌ '技术': 不存在
❌ text:期望职位: 未找到
```

---

## 📝 下一步

### 如果成功

1. 查看保存的HTML文件
2. 分析职位列表的结构
3. 编写爬虫代码提取职位数据

### 如果失败

1. 检查浏览器是否打开
2. 检查是否需要登录
3. 检查页面结构是否已更改

---

## 💡 调试技巧

### 1. 查看浏览器窗口

脚本会打开浏览器窗口，你可以：
- 看到实际页面
- 手动验证
- 调试问题

### 2. 查看保存的HTML

```bash
# 查看页面源码
cat backend/resume_editor/data/boss_page_structure.html

# 搜索关键词
grep "技术" backend/resume_editor/data/boss_page_structure.html
```

### 3. 修改脚本

如果需要调整，可以修改：
- 选择器
- 等待时间
- 搜索关键词

---

## 📚 相关文件

- 检查脚本：`backend/resume_editor/platforms/check_boss_page.py`
- 完整爬虫：`backend/resume_editor/platforms/boss_job_list_scraper.py`
- 保存的HTML：`backend/resume_editor/data/boss_page_structure.html`

---

## 🎉 开始吧！

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/check_boss_page.py
```

---

**祝你好运！** 🚀
