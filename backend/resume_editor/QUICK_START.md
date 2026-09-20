# BOSS直聘期望职位爬虫 - 快速开始

## 🚀 立即开始

### 1. 运行爬虫脚本

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/boss_job_list_scraper.py
```

### 2. 选择方法

建议从**方法4**开始（手动交互），因为：
- 可以看到实际操作
- 可以手动验证
- 最容易成功

### 3. 查看结果

成功后，查看保存的文件：
```bash
cat backend/resume_editor/data/boss_resume_manual.html | grep "技术\|产品\|设计"
```

---

## 📊 4种方法对比

| 方法 | 难度 | 成功率 | 说明 |
|------|------|--------|------|
| 方法1 | ⭐⭐ | 中等 | 自动查找输入框并点击 |
| 方法2 | ⭐ | 低 | 尝试不同的选择器 |
| 方法3 | ⭐ | 中等 | 检查页面结构 |
| 方法4 | ⭐⭐⭐ | 高 | 手动操作，最可靠 |

---

## 🎯 推荐流程

### 第一次运行：方法4（手动交互）

1. 运行脚本
2. 选择方法4
3. 手动操作：
   - 点击期望职位的编辑按钮
   - 点击期望职位的输入框
   - 等待职位列表弹出
4. 按回车键继续
5. 查看保存的HTML文件

### 第二次运行：方法3（检查结构）

1. 运行脚本
2. 选择方法3
3. 查看输出的关键词
4. 分析HTML结构

### 第三次运行：方法1（自动查找）

1. 运行脚本
2. 选择方法1
3. 查看自动查找的结果
4. 根据结果调整代码

---

## 📝 成功后的下一步

### 1. 分析HTML结构

```bash
# 查看保存的HTML
cat backend/resume_editor/data/boss_resume_manual.html

# 搜索职位分类
grep -i "技术\|产品\|设计" backend/resume_editor/data/boss_resume_manual.html

# 搜索具体的职位
grep -i "后端开发\|前端开发\|Java\|Python" backend/resume_editor/data/boss_resume_manual.html
```

### 2. 提取职位数据

根据HTML结构，编写代码提取：
- 一级分类（技术、产品、设计等）
- 二级分类（后端开发、前端开发等）
- 三级分类（Java、Python等）

### 3. 保存到JSON

```python
import json

job_categories = {
    "技术": {
        "后端开发": ["Java", "C++", "PHP", "Python"],
        "前端开发": ["Web前端", "JavaScript", "HTML5"],
        ...
    },
    "产品": {
        "产品经理": ["产品经理", "产品助理", "产品总监"],
        ...
    },
    ...
}

with open('boss_job_categories.json', 'w', encoding='utf-8') as f:
    json.dump(job_categories, f, ensure_ascii=False, indent=2)
```

---

## 💡 调试技巧

### 1. 查看浏览器窗口

脚本会打开浏览器窗口，你可以：
- 看到实际操作
- 手动验证
- 调试问题

### 2. 查看保存的HTML

```bash
# 查看页面源码
cat backend/resume_editor/data/boss_resume_manual.html

# 搜索关键词
grep "技术" backend/resume_editor/data/boss_resume_manual.html
```

### 3. 修改脚本

如果某种方法失败，可以：
- 调整选择器
- 增加等待时间
- 尝试其他方法

---

## 🎉 成功标志

### 你应该看到：

```
✅ 找到期望职位区域
✅ 找到编辑按钮，准备点击...
✅ 点击成功
✅ 找到输入框，准备点击...
✅ 点击成功
✅ '技术': 存在
✅ '产品': 存在
✅ '设计': 存在
```

### 保存的文件应该包含：

```html
<div class="job-category">
  <div class="category-item">技术</div>
  <div class="category-item">产品</div>
  <div class="category-item">设计</div>
  ...
</div>
```

---

## 📚 相关文件

- 爬虫脚本：`backend/resume_editor/platforms/boss_job_list_scraper.py`
- 使用说明：`backend/resume_editor/JOB_LIST_SCRAPER_GUIDE.md`
- 保存的HTML：`backend/resume_editor/data/boss_resume_manual.html`

---

## 🚀 开始吧！

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/boss_job_list_scraper.py
```

选择**方法4**，手动操作，看看会发生什么！

---

**祝你好运！** 🎉
