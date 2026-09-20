# BOSS直聘期望职位列表爬虫 - 使用说明

## 📋 脚本说明

这个脚本包含4种方法，让你可以逐步尝试爬取BOSS直聘的期望职位列表。

---

## 🚀 使用步骤

### 步骤1：运行脚本

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/boss_job_list_scraper.py
```

### 步骤2：选择方法

脚本会显示菜单：
```
选择方法：
1. 方法1：查找期望职位输入框并点击
2. 方法2：尝试不同的选择器
3. 方法3：检查页面结构
4. 方法4：手动交互
5. 运行所有方法
```

### 步骤3：查看输出

根据选择的方法，脚本会：
1. 打开浏览器
2. 访问BOSS直聘简历页面
3. 尝试各种操作
4. 输出结果

---

## 📊 方法说明

### 方法1：查找期望职位输入框并点击

**目的**：尝试找到并点击期望职位的输入框

**步骤**：
1. 访问BOSS直聘简历页面
2. 查找期望职位区域
3. 查找编辑按钮并点击
4. 查找输入框并点击
5. 检查是否有职位列表弹出

**输出**：
- ✅ 成功：显示找到的元素
- ❌ 失败：显示错误信息

---

### 方法2：尝试不同的选择器

**目的**：尝试多种CSS选择器，找到正确的元素

**步骤**：
1. 访问BOSS直聘简历页面
2. 尝试多种选择器
3. 显示找到的元素数量和文本

**输出**：
```
✅ text:期望职位: 1 个元素
   文本: 期望职位
✅ ka:user-resume-edit-expectation0: 1 个元素
   文本: 编辑
❌ css:.job-category: 失败 - 未找到元素
```

---

### 方法3：检查页面结构

**目的**：分析页面HTML结构，找到关键词

**步骤**：
1. 访问BOSS直聘简历页面
2. 获取页面源码
3. 搜索关键词
4. 搜索职位分类
5. 保存页面源码

**输出**：
```
✅ '期望职位': 出现 5 次
✅ '选择期望职位': 出现 1 次
✅ '技术': 存在
✅ '产品': 存在
✅ '设计': 存在
```

**保存文件**：`backend/resume_editor/data/boss_resume_page.html`

---

### 方法4：手动交互

**目的**：让你手动操作，然后获取操作后的页面

**步骤**：
1. 访问BOSS直聘简历页面
2. 等待你手动操作：
   - 点击期望职位的编辑按钮
   - 点击期望职位的输入框
   - 等待职位列表弹出
3. 按回车键继续
4. 获取操作后的页面源码

**输出**：
```
2. 请手动操作：
   - 点击期望职位的编辑按钮
   - 点击期望职位的输入框
   - 等待职位列表弹出
   - 操作完成后，按回车键继续...

3. 获取操作后的页面源码...
   页面源码长度: 264173 字符

4. 搜索职位分类...
   ✅ '技术': 存在
   ✅ '产品': 存在
   ✅ '设计': 存在
```

**保存文件**：`backend/resume_editor/data/boss_resume_manual.html`

---

## 🔧 调试技巧

### 1. 查看保存的HTML文件

```bash
# 查看页面源码
cat backend/resume_editor/data/boss_resume_page.html | grep "技术\|产品\|设计"

# 查看手动操作后的页面
cat backend/resume_editor/data/boss_resume_manual.html | grep "技术\|产品\|设计"
```

### 2. 搜索职位分类

```bash
# 搜索一级分类
grep -i "技术\|产品\|设计\|运营\|市场\|销售" backend/resume_editor/data/boss_resume_page.html

# 搜索二级分类
grep -i "后端开发\|前端开发\|移动开发" backend/resume_editor/data/boss_resume_page.html

# 搜索三级分类
grep -i "Java\|Python\|C++" backend/resume_editor/data/boss_resume_page.html
```

### 3. 查看元素结构

```bash
# 查看class属性
grep -o 'class="[^"]*"' backend/resume_editor/data/boss_resume_page.html | sort | uniq

# 查看包含category的class
grep -o 'class="[^"]*category[^"]*"' backend/resume_editor/data/boss_resume_page.html
```

---

## 🎯 预期结果

### 成功情况

如果成功找到职位列表，你应该看到：

```
✅ 找到期望职位区域
✅ 找到编辑按钮，准备点击...
✅ 点击成功
✅ 找到输入框，准备点击...
✅ 点击成功
✅ 找到元素: css:.job-category (20 个)
✅ 找到元素: css:.position-list (50 个)
```

### 失败情况

如果失败，你应该看到：

```
❌ 未找到期望职位区域
❌ 未找到编辑按钮
❌ 未找到输入框
❌ 未找到职位列表元素
```

---

## 📝 下一步

### 如果成功

1. 查看保存的HTML文件
2. 分析职位列表的结构
3. 编写爬虫代码提取职位数据

### 如果失败

1. 尝试其他方法
2. 检查页面结构
3. 可能需要手动登录

---

## 💡 常见问题

### Q1：浏览器没有打开

**原因**：DrissionPage配置问题

**解决**：
```bash
# 检查Edge浏览器路径
ls -la "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"

# 检查端口是否被占用
lsof -i :9236
```

### Q2：找不到编辑按钮

**原因**：页面结构可能已更改

**解决**：
1. 使用方法2尝试不同的选择器
2. 使用方法3检查页面结构
3. 使用方法4手动操作

### Q3：职位列表没有弹出

**原因**：JavaScript动态加载

**解决**：
1. 增加等待时间
2. 使用方法4手动操作
3. 检查网络请求

---

## 📚 相关文件

- 爬虫脚本：`backend/resume_editor/platforms/boss_job_list_scraper.py`
- 保存的HTML：`backend/resume_editor/data/boss_resume_page.html`
- 手动操作的HTML：`backend/resume_editor/data/boss_resume_manual.html`

---

## 🎉 成功示例

如果成功，你应该能够：

1. 找到职位列表的HTML结构
2. 提取一级分类（技术、产品、设计等）
3. 提取二级分类（后端开发、前端开发等）
4. 提取三级分类（Java、Python等）
5. 保存到JSON文件

---

**最后更新**：2026-07-21
**版本**：1.0.0
