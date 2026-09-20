# BOSS直聘职位分类完整爬取器 - 使用说明

## 📋 脚本说明

这个脚本会：
1. 访问BOSS直聘简历页面
2. 点击编辑按钮
3. 点击期望职位输入框
4. **遍历所有一级分类**，记录名称
5. **点击每个一级分类**，遍历二级分类，记录
6. **点击每个二级分类**，遍历三级分类，记录
7. 保存到JSON文件

---

## 🚀 使用步骤

### 步骤1：运行脚本

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/boss_full_scraper.py
```

### 步骤2：手动登录（如果需要）

脚本会检查登录状态，如果未登录，会提示你手动扫码登录。

### 步骤3：等待脚本完成

脚本会自动遍历所有分类，并实时输出进度：

```
📂 一级分类: 技术
   📁 二级分类: 后端开发
      📄 三级分类: Java
      📄 三级分类: C++
      📄 三级分类: Python
      ...
   📁 二级分类: 前端开发
      📄 三级分类: Web前端
      📄 三级分类: JavaScript
      ...
📂 一级分类: 产品
   📁 二级分类: 产品经理
      📄 三级分类: 产品经理
      📄 三级分类: 产品助理
      ...
```

### 步骤4：查看结果

脚本会保存到：
```
backend/resume_editor/data/boss_categories_full.json
```

---

## 📊 预期输出

```json
{
  "技术": {
    "后端开发": ["Java", "C++", "PHP", "Python", ...],
    "前端开发": ["Web前端", "JavaScript", ...],
    "移动开发": ["Android", "iOS", ...],
    ...
  },
  "产品": {
    "产品经理": ["产品经理", "产品助理", ...],
    ...
  },
  "设计": {
    "视觉设计": ["UI设计师", "平面设计师", ...],
    ...
  },
  ...
}
```

---

## 🎯 优势

1. **完全一致** - 所有分类名称与BOSS官网完全一致
2. **不会遗漏** - 自动遍历所有分类
3. **自动记录** - 不需要手动比对
4. **后期同步** - 同步回BOSS官网时，名称完全匹配

---

## 🔧 技术细节

### 使用的工具
- **DrissionPage** - 浏览器自动化
- **Edge浏览器** - 与BOSS直聘兼容

### 等待时间
- 一级分类点击后等待2秒
- 二级分类点击后等待2秒
- 确保动态加载的内容完全加载

### 错误处理
- 如果某个分类获取失败，会记录错误并继续
- 确保不会因为单个错误而中断整个流程

---

## 📚 相关文件

- 爬取脚本：`backend/resume_editor/platforms/boss_full_scraper.py`
- 输出文件：`backend/resume_editor/data/boss_categories_full.json`
- 前端数据：`frontend/lib/job-categories.ts`（需要更新）

---

## 🎯 下一步

### 1. 运行脚本
```bash
python3 resume_editor/platforms/boss_full_scraper.py
```

### 2. 更新前端数据
将爬取的JSON数据转换为前端可用的格式，更新 `job-categories.ts`

### 3. 测试功能
启动服务，测试期望职位选择器

---

## 💡 注意事项

1. **需要登录** - 必须先登录BOSS直聘
2. **需要等待** - 脚本会自动等待动态加载
3. **可能较慢** - 遍历所有分类需要一定时间
4. **网络依赖** - 需要稳定的网络连接

---

## 🎉 开始吧！

```bash
cd <repo-root>/backend
python3 resume_editor/platforms/boss_full_scraper.py
```

**祝你好运！** 🚀
