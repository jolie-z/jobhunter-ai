// BOSS直聘驻外选项数据（API + Vue实例爬取，2026-07-23）
// 10大洲 + 各国, 77种语言, 12个时长选项

export interface CountryRegion {
  code: number
  name: string
  flag: number  // 1=全部X
  subLevelModelList: CountryItem[] | null
}

export interface CountryItem {
  code: number
  name: string
  flag: number  // 1=全部X
}

export interface LanguageItem {
  id: number
  name: string
  emoji: string
  code: number
}

export interface DurationItem {
  id: number
  name: string
  code: number
}

export const COUNTRY_MAX_SELECT = 5
export const LANGUAGE_MAX_SELECT = 5

export const countryRegions: CountryRegion[] = [
  {
    code: 1,
    name: "不限",
    flag: 1,
    subLevelModelList: [
      { code: 1, name: "不限国家/地区", flag: 1 }
    ]
  },
  {
    code: 2,
    name: "亚洲",
    flag: 0,
    subLevelModelList: [
      { code: 2, name: "全部亚洲", flag: 1 },
      { code: 104, name: "日本", flag: 0 },
      { code: 106, name: "印度尼西亚", flag: 0 },
      { code: 107, name: "越南", flag: 0 },
      { code: 108, name: "印度", flag: 0 },
      { code: 110, name: "泰国", flag: 0 },
      { code: 112, name: "菲律宾", flag: 0 },
      { code: 113, name: "柬埔寨", flag: 0 },
      { code: 115, name: "新加坡", flag: 0 },
      { code: 119, name: "韩国", flag: 0 },
      { code: 122, name: "马来西亚", flag: 0 },
      { code: 125, name: "老挝", flag: 0 },
      { code: 133, name: "缅甸", flag: 0 },
      { code: 136, name: "土耳其", flag: 0 },
      { code: 137, name: "巴基斯坦", flag: 0 },
      { code: 139, name: "阿联酋", flag: 0 },
      { code: 147, name: "伊拉克", flag: 0 },
      { code: 148, name: "哈萨克斯坦", flag: 0 },
      { code: 149, name: "沙特阿拉伯", flag: 0 },
      { code: 150, name: "朝鲜", flag: 0 },
      { code: 152, name: "乌兹别克斯坦", flag: 0 },
      { code: 154, name: "孟加拉国", flag: 0 },
      { code: 166, name: "伊朗", flag: 0 },
      { code: 171, name: "阿曼", flag: 0 },
      { code: 175, name: "东帝汶", flag: 0 },
      { code: 176, name: "斯里兰卡", flag: 0 },
      { code: 186, name: "卡塔尔", flag: 0 },
      { code: 189, name: "文莱", flag: 0 },
      { code: 191, name: "马尔代夫", flag: 0 },
      { code: 194, name: "吉尔吉斯斯坦", flag: 0 },
      { code: 200, name: "以色列", flag: 0 },
      { code: 201, name: "格鲁吉亚", flag: 0 },
      { code: 202, name: "巴林", flag: 0 },
      { code: 203, name: "约旦", flag: 0 },
      { code: 204, name: "尼泊尔", flag: 0 },
      { code: 219, name: "科威特", flag: 0 },
      { code: 226, name: "阿塞拜疆", flag: 0 },
      { code: 228, name: "阿富汗", flag: 0 },
      { code: 234, name: "土库曼斯坦", flag: 0 },
      { code: 239, name: "塔吉克斯坦", flag: 0 },
      { code: 250, name: "不丹", flag: 0 },
      { code: 254, name: "亚美尼亚", flag: 0 },
      { code: 257, name: "巴勒斯坦", flag: 0 },
      { code: 258, name: "黎巴嫩", flag: 0 },
      { code: 259, name: "蒙古", flag: 0 },
      { code: 260, name: "叙利亚", flag: 0 },
      { code: 261, name: "也门", flag: 0 }
    ]
  },
  {
    code: 3,
    name: "非洲",
    flag: 0,
    subLevelModelList: [
      { code: 3, name: "全部非洲", flag: 1 },
      { code: 123, name: "尼日利亚", flag: 0 },
      { code: 129, name: "肯尼亚", flag: 0 },
      { code: 131, name: "埃及", flag: 0 },
      { code: 132, name: "南非", flag: 0 },
      { code: 134, name: "阿尔及利亚", flag: 0 },
      { code: 135, name: "加纳", flag: 0 },
      { code: 138, name: "埃塞俄比亚", flag: 0 },
      { code: 140, name: "安哥拉", flag: 0 },
      { code: 142, name: "几内亚", flag: 0 },
      { code: 144, name: "坦桑尼亚", flag: 0 },
      { code: 145, name: "科特迪瓦", flag: 0 },
      { code: 151, name: "津巴布韦", flag: 0 },
      { code: 153, name: "乌干达", flag: 0 },
      { code: 155, name: "赞比亚", flag: 0 },
      { code: 156, name: "中非", flag: 0 },
      { code: 160, name: "喀麦隆", flag: 0 },
      { code: 163, name: "加蓬", flag: 0 },
      { code: 167, name: "莫桑比克", flag: 0 },
      { code: 169, name: "贝宁", flag: 0 },
      { code: 173, name: "摩洛哥", flag: 0 },
      { code: 178, name: "塞内加尔", flag: 0 },
      { code: 181, name: "乍得", flag: 0 },
      { code: 182, name: "卢旺达", flag: 0 },
      { code: 183, name: "尼日尔", flag: 0 },
      { code: 192, name: "毛里塔尼亚", flag: 0 },
      { code: 196, name: "马达加斯加", flag: 0 },
      { code: 198, name: "赤道几内亚", flag: 0 },
      { code: 206, name: "纳米比亚", flag: 0 },
      { code: 208, name: "布基纳法索", flag: 0 },
      { code: 209, name: "毛里求斯", flag: 0 },
      { code: 211, name: "博茨瓦纳", flag: 0 },
      { code: 212, name: "马拉维", flag: 0 },
      { code: 213, name: "苏丹", flag: 0 },
      { code: 214, name: "南苏丹", flag: 0 },
      { code: 221, name: "塞舌尔", flag: 0 },
      { code: 222, name: "布隆迪", flag: 0 },
      { code: 223, name: "利比里亚", flag: 0 },
      { code: 227, name: "塞拉利昂", flag: 0 },
      { code: 232, name: "吉布提", flag: 0 },
      { code: 241, name: "莱索托", flag: 0 },
      { code: 243, name: "厄立特里亚", flag: 0 },
      { code: 253, name: "佛得角", flag: 0 },
      { code: 262, name: "多哥", flag: 0 },
      { code: 263, name: "冈比亚", flag: 0 },
      { code: 264, name: "刚果(布)", flag: 0 },
      { code: 265, name: "刚果(金)", flag: 0 },
      { code: 266, name: "几内亚比绍", flag: 0 },
      { code: 267, name: "科摩罗", flag: 0 },
      { code: 268, name: "利比亚", flag: 0 },
      { code: 269, name: "马里", flag: 0 },
      { code: 270, name: "圣多美和普林西比", flag: 0 },
      { code: 271, name: "斯威士兰", flag: 0 },
      { code: 272, name: "索马里", flag: 0 },
      { code: 273, name: "突尼斯", flag: 0 }
    ]
  },
  {
    code: 4,
    name: "欧洲",
    flag: 0,
    subLevelModelList: [
      { code: 4, name: "全部欧洲", flag: 1 },
      { code: 109, name: "俄罗斯", flag: 0 },
      { code: 111, name: "西班牙", flag: 0 },
      { code: 116, name: "德国", flag: 0 },
      { code: 124, name: "葡萄牙", flag: 0 },
      { code: 126, name: "英国", flag: 0 },
      { code: 127, name: "意大利", flag: 0 },
      { code: 130, name: "法国", flag: 0 },
      { code: 146, name: "匈牙利", flag: 0 },
      { code: 158, name: "塞尔维亚", flag: 0 },
      { code: 162, name: "荷兰", flag: 0 },
      { code: 165, name: "希腊", flag: 0 },
      { code: 168, name: "丹麦", flag: 0 },
      { code: 170, name: "波兰", flag: 0 },
      { code: 172, name: "瑞士", flag: 0 },
      { code: 177, name: "白俄罗斯", flag: 0 },
      { code: 179, name: "捷克", flag: 0 },
      { code: 184, name: "摩纳哥", flag: 0 },
      { code: 185, name: "乌克兰", flag: 0 },
      { code: 187, name: "比利时", flag: 0 },
      { code: 188, name: "奥地利", flag: 0 },
      { code: 193, name: "瑞典", flag: 0 },
      { code: 195, name: "罗马尼亚", flag: 0 },
      { code: 199, name: "保加利亚", flag: 0 },
      { code: 210, name: "挪威", flag: 0 },
      { code: 215, name: "黑山", flag: 0 },
      { code: 216, name: "卢森堡", flag: 0 },
      { code: 217, name: "塞浦路斯", flag: 0 },
      { code: 220, name: "芬兰", flag: 0 },
      { code: 229, name: "拉脱维亚", flag: 0 },
      { code: 233, name: "阿尔巴尼亚", flag: 0 },
      { code: 238, name: "爱尔兰", flag: 0 },
      { code: 245, name: "立陶宛", flag: 0 },
      { code: 246, name: "爱沙尼亚", flag: 0 },
      { code: 252, name: "克罗地亚", flag: 0 },
      { code: 274, name: "安道尔", flag: 0 },
      { code: 275, name: "北马其顿", flag: 0 },
      { code: 276, name: "冰岛", flag: 0 },
      { code: 277, name: "波黑", flag: 0 },
      { code: 278, name: "梵蒂冈", flag: 0 },
      { code: 279, name: "列支敦士登", flag: 0 },
      { code: 280, name: "马耳他", flag: 0 },
      { code: 281, name: "摩尔多瓦", flag: 0 },
      { code: 282, name: "圣马力诺", flag: 0 },
      { code: 283, name: "斯洛伐克", flag: 0 },
      { code: 284, name: "斯洛文尼亚", flag: 0 }
    ]
  },
  {
    code: 5,
    name: "南美洲",
    flag: 0,
    subLevelModelList: [
      { code: 6, name: "全部南美洲", flag: 1 },
      { code: 117, name: "巴西", flag: 0 },
      { code: 143, name: "智利", flag: 0 },
      { code: 157, name: "哥伦比亚", flag: 0 },
      { code: 159, name: "阿根廷", flag: 0 },
      { code: 164, name: "秘鲁", flag: 0 },
      { code: 174, name: "玻利维亚", flag: 0 },
      { code: 180, name: "厄瓜多尔", flag: 0 },
      { code: 237, name: "委内瑞拉", flag: 0 },
      { code: 244, name: "圭亚那", flag: 0 },
      { code: 255, name: "巴拉圭", flag: 0 },
      { code: 256, name: "苏里南", flag: 0 },
      { code: 292, name: "乌拉圭", flag: 0 }
    ]
  },
  {
    code: 6,
    name: "北美洲",
    flag: 0,
    subLevelModelList: [
      { code: 5, name: "全部北美洲", flag: 1 },
      { code: 105, name: "美国", flag: 0 },
      { code: 114, name: "墨西哥", flag: 0 },
      { code: 118, name: "加拿大", flag: 0 },
      { code: 121, name: "海地", flag: 0 },
      { code: 161, name: "古巴", flag: 0 },
      { code: 190, name: "多米尼克", flag: 0 },
      { code: 197, name: "巴拿马", flag: 0 },
      { code: 207, name: "多米尼加", flag: 0 },
      { code: 224, name: "危地马拉", flag: 0 },
      { code: 230, name: "尼加拉瓜", flag: 0 },
      { code: 231, name: "特立尼达和多巴哥", flag: 0 },
      { code: 240, name: "圣卢西亚", flag: 0 },
      { code: 247, name: "洪都拉斯", flag: 0 },
      { code: 248, name: "巴哈马", flag: 0 },
      { code: 249, name: "巴巴多斯", flag: 0 },
      { code: 251, name: "格林纳达", flag: 0 },
      { code: 285, name: "安提瓜和巴布达", flag: 0 },
      { code: 286, name: "伯利兹", flag: 0 },
      { code: 287, name: "哥斯达黎加", flag: 0 },
      { code: 288, name: "萨尔瓦多", flag: 0 },
      { code: 289, name: "圣基茨和尼维斯", flag: 0 },
      { code: 290, name: "圣文森特和格林纳丁斯", flag: 0 },
      { code: 291, name: "牙买加", flag: 0 }
    ]
  },
  {
    code: 7,
    name: "大洋洲",
    flag: 0,
    subLevelModelList: [
      { code: 7, name: "全部大洋洲", flag: 1 },
      { code: 120, name: "澳大利亚", flag: 0 },
      { code: 141, name: "新西兰", flag: 0 },
      { code: 205, name: "汤加", flag: 0 },
      { code: 218, name: "所罗门群岛", flag: 0 },
      { code: 225, name: "帕劳", flag: 0 },
      { code: 235, name: "瓦努阿图", flag: 0 },
      { code: 242, name: "斐济", flag: 0 },
      { code: 293, name: "巴布亚新几内亚", flag: 0 },
      { code: 294, name: "基里巴斯", flag: 0 },
      { code: 295, name: "库克群岛", flag: 0 },
      { code: 296, name: "马绍尔群岛", flag: 0 },
      { code: 297, name: "密克罗尼西亚联邦", flag: 0 },
      { code: 298, name: "瑙鲁", flag: 0 },
      { code: 299, name: "纽埃", flag: 0 },
      { code: 300, name: "萨摩亚", flag: 0 },
      { code: 301, name: "图瓦卢", flag: 0 }
    ]
  },
  {
    code: 8,
    name: "中国港澳台",
    flag: 0,
    subLevelModelList: [
      { code: 101, name: "中国香港", flag: 0 },
      { code: 102, name: "中国澳门", flag: 0 },
      { code: 103, name: "中国台湾", flag: 0 }
    ]
  },
  {
    code: 9,
    name: "中东地区",
    flag: 0,
    subLevelModelList: [
      { code: 8, name: "全部中东地区", flag: 1 },
      { code: 131, name: "埃及", flag: 0 },
      { code: 134, name: "阿尔及利亚", flag: 0 },
      { code: 136, name: "土耳其", flag: 0 },
      { code: 137, name: "巴基斯坦", flag: 0 },
      { code: 139, name: "阿联酋", flag: 0 },
      { code: 147, name: "伊拉克", flag: 0 },
      { code: 148, name: "哈萨克斯坦", flag: 0 },
      { code: 149, name: "沙特阿拉伯", flag: 0 },
      { code: 152, name: "乌兹别克斯坦", flag: 0 },
      { code: 166, name: "伊朗", flag: 0 },
      { code: 171, name: "阿曼", flag: 0 },
      { code: 173, name: "摩洛哥", flag: 0 },
      { code: 186, name: "卡塔尔", flag: 0 },
      { code: 192, name: "毛里塔尼亚", flag: 0 },
      { code: 194, name: "吉尔吉斯斯坦", flag: 0 },
      { code: 200, name: "以色列", flag: 0 },
      { code: 201, name: "格鲁吉亚", flag: 0 },
      { code: 202, name: "巴林", flag: 0 },
      { code: 203, name: "约旦", flag: 0 },
      { code: 214, name: "南苏丹", flag: 0 },
      { code: 219, name: "科威特", flag: 0 },
      { code: 228, name: "阿富汗", flag: 0 },
      { code: 232, name: "吉布提", flag: 0 },
      { code: 234, name: "土库曼斯坦", flag: 0 },
      { code: 243, name: "厄立特里亚", flag: 0 },
      { code: 254, name: "亚美尼亚", flag: 0 },
      { code: 257, name: "巴勒斯坦", flag: 0 },
      { code: 258, name: "黎巴嫩", flag: 0 },
      { code: 260, name: "叙利亚", flag: 0 },
      { code: 261, name: "也门", flag: 0 },
      { code: 267, name: "科摩罗", flag: 0 },
      { code: 268, name: "利比亚", flag: 0 },
      { code: 272, name: "索马里", flag: 0 },
      { code: 273, name: "突尼斯", flag: 0 }
    ]
  },
  {
    code: 10,
    name: "东南亚",
    flag: 0,
    subLevelModelList: [
      { code: 9, name: "全部东南亚", flag: 1 },
      { code: 106, name: "印度尼西亚", flag: 0 },
      { code: 107, name: "越南", flag: 0 },
      { code: 110, name: "泰国", flag: 0 },
      { code: 112, name: "菲律宾", flag: 0 },
      { code: 113, name: "柬埔寨", flag: 0 },
      { code: 115, name: "新加坡", flag: 0 },
      { code: 122, name: "马来西亚", flag: 0 },
      { code: 125, name: "老挝", flag: 0 },
      { code: 133, name: "缅甸", flag: 0 },
      { code: 175, name: "东帝汶", flag: 0 },
      { code: 189, name: "文莱", flag: 0 }
    ]
  },
]

export const allLanguages: LanguageItem[] = [
  { id: 1, name: "英语", emoji: "🇬🇧", code: 1 },
  { id: 2, name: "粤语", emoji: "", code: 2 },
  { id: 3, name: "日语", emoji: "🇯🇵", code: 3 },
  { id: 4, name: "西班牙语", emoji: "🇪🇸", code: 4 },
  { id: 5, name: "法语", emoji: "🇫🇷", code: 5 },
  { id: 6, name: "德语", emoji: "🇩🇪", code: 6 },
  { id: 7, name: "俄语", emoji: "🇷🇺", code: 7 },
  { id: 8, name: "葡萄牙语", emoji: "🇵🇹", code: 8 },
  { id: 9, name: "意大利语", emoji: "🇮🇹", code: 9 },
  { id: 10, name: "韩语", emoji: "🇰🇷", code: 10 },
  { id: 11, name: "土耳其语", emoji: "🇹🇷", code: 11 },
  { id: 12, name: "阿拉伯语", emoji: "🇸🇦", code: 12 },
  { id: 13, name: "泰语", emoji: "🇹🇭", code: 13 },
  { id: 14, name: "越南语", emoji: "🇻🇳", code: 14 },
  { id: 15, name: "阿塞拜疆语", emoji: "🇦🇿", code: 15 },
  { id: 16, name: "阿尔巴尼亚语", emoji: "🇦🇱", code: 16 },
  { id: 17, name: "爱尔兰语", emoji: "🇮🇪", code: 17 },
  { id: 18, name: "爱沙尼亚语", emoji: "🇪🇪", code: 18 },
  { id: 19, name: "阿非利卡语", emoji: "", code: 19 },
  { id: 20, name: "波斯语", emoji: "", code: 20 },
  { id: 21, name: "白俄罗斯语", emoji: "🇧🇾", code: 21 },
  { id: 22, name: "保加利亚语", emoji: "🇧🇬", code: 22 },
  { id: 23, name: "冰岛语", emoji: "🇮🇸", code: 23 },
  { id: 24, name: "波斯尼亚语", emoji: "🇧🇦", code: 24 },
  { id: 25, name: "波兰语", emoji: "🇵🇱", code: 25 },
  { id: 26, name: "朝鲜语", emoji: "🇰🇵", code: 26 },
  { id: 27, name: "达里语", emoji: "🇦🇫", code: 27 },
  { id: 28, name: "德顿语", emoji: "", code: 28 },
  { id: 29, name: "丹麦语", emoji: "🇩🇰", code: 29 },
  { id: 30, name: "俄罗斯语", emoji: "🇷🇺", code: 30 },
  { id: 31, name: "芬兰语", emoji: "🇫🇮", code: 31 },
  { id: 32, name: "格鲁吉亚语", emoji: "🇬🇪", code: 32 },
  { id: 33, name: "高棉语", emoji: "🇰🇭", code: 33 },
  { id: 34, name: "哈萨克语", emoji: "🇰🇿", code: 34 },
  { id: 35, name: "荷兰语", emoji: "🇳🇱", code: 35 },
  { id: 36, name: "黑山语", emoji: "🇲🇪", code: 36 },
  { id: 37, name: "吉尔吉斯语", emoji: "🇰🇬", code: 37 },
  { id: 38, name: "捷克语", emoji: "🇨🇿", code: 38 },
  { id: 39, name: "科摩罗语", emoji: "", code: 39 },
  { id: 40, name: "克罗地亚语", emoji: "🇭🇷", code: 40 },
  { id: 41, name: "库尔德语", emoji: "🇮🇷", code: 41 },
  { id: 42, name: "克里奥尔语", emoji: "🇭🇹", code: 42 },
  { id: 43, name: "老挝语", emoji: "🇱🇦", code: 43 },
  { id: 44, name: "卢旺达语", emoji: "🇷🇼", code: 44 },
  { id: 45, name: "拉脱维亚语", emoji: "🇱🇻", code: 45 },
  { id: 46, name: "立陶宛语", emoji: "🇱🇹", code: 46 },
  { id: 47, name: "罗马尼亚语", emoji: "🇷🇴", code: 47 },
  { id: 48, name: "拉丁语", emoji: "🇻🇦", code: 48 },
  { id: 49, name: "马来语", emoji: "🇲🇾", code: 49 },
  { id: 50, name: "蒙古语", emoji: "🇲🇳", code: 50 },
  { id: 51, name: "孟加拉语", emoji: "🇧🇩", code: 51 },
  { id: 52, name: "缅甸语", emoji: "🇲🇲", code: 52 },
  { id: 53, name: "马其顿语", emoji: "🇲🇰", code: 53 },
  { id: 54, name: "马耳他语", emoji: "🇲🇹", code: 54 },
  { id: 55, name: "摩尔多瓦语", emoji: "🇲🇩", code: 55 },
  { id: 56, name: "尼泊尔语", emoji: "🇳🇵", code: 56 },
  { id: 57, name: "挪威语", emoji: "🇳🇴", code: 57 },
  { id: 58, name: "普什图语", emoji: "🇦🇫", code: 58 },
  { id: 59, name: "瑞典语", emoji: "🇸🇪", code: 59 },
  { id: 60, name: "塞尔维亚语", emoji: "🇷🇸", code: 60 },
  { id: 61, name: "斯洛伐克语", emoji: "🇸🇰", code: 61 },
  { id: 62, name: "斯洛文尼亚语", emoji: "🇸🇮", code: 62 },
  { id: 63, name: "萨米语", emoji: "", code: 63 },
  { id: 64, name: "泰米尔语", emoji: "🇮🇳", code: 64 },
  { id: 65, name: "塔吉克语", emoji: "🇹🇯", code: 65 },
  { id: 66, name: "土库曼语", emoji: "🇹🇲", code: 66 },
  { id: 67, name: "乌尔都语", emoji: "🇵🇰", code: 67 },
  { id: 68, name: "乌兹别克语", emoji: "🇺🇿", code: 68 },
  { id: 69, name: "乌克兰语", emoji: "🇺🇦", code: 69 },
  { id: 70, name: "希伯来语", emoji: "🇮🇱", code: 70 },
  { id: 71, name: "希腊语", emoji: "🇬🇷", code: 71 },
  { id: 72, name: "匈牙利语", emoji: "🇭🇺", code: 72 },
  { id: 73, name: "亚美尼亚语", emoji: "🇦🇲", code: 73 },
  { id: 74, name: "印度语", emoji: "🇮🇳", code: 74 },
  { id: 75, name: "印尼语", emoji: "🇮🇩", code: 75 },
  { id: 77, name: "宗卡语", emoji: "🇧🇹", code: 77 },
  { id: 78, name: "卢森堡语", emoji: "", code: 78 },
]

export const durationOptions: DurationItem[] = [
  { id: 11, name: "偶尔出差", code: 11 },
  { id: 12, name: "频繁出差", code: 12 },
  { id: 10, name: "1个月内", code: 10 },
  { id: 1, name: "1~3个月", code: 1 },
  { id: 2, name: "3~6个月", code: 2 },
  { id: 3, name: "6~12个月", code: 3 },
  { id: 4, name: "1年", code: 4 },
  { id: 5, name: "2年", code: 5 },
  { id: 6, name: "3年", code: 6 },
  { id: 7, name: "4年", code: 7 },
  { id: 8, name: "5年以上", code: 8 },
  { id: 9, name: "长期驻外", code: 9 },
]

// 根据国家/地区code推荐语言
export const regionLanguageMap: Record<number, number[]> = {
  2: [3, 10, 13, 14, 49, 75], // 亚洲
  3: [5, 12, 8], // 非洲
  4: [1, 5, 6, 4, 9, 7], // 欧洲
  5: [4, 8], // 南美洲
  6: [1, 4, 5], // 北美洲
  7: [1], // 大洋洲
  8: [1, 2], // 中国港澳台
  9: [1, 12, 11], // 中东地区
  10: [1, 13, 14, 49, 75], // 东南亚
}
