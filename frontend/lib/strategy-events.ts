// /strategy 页内免刷新切换板块的自定义事件名（中立单点：
// use-strategy-store 负责监听，新手引导等组件负责派发，避免组件层与 hooks 层互相引常量）

export const STRATEGY_SET_SECTION_EVENT = "strategy:set-section"

/** 派发页内切换事件（仅当已处于 /strategy 页时有效；跨页请用带 ?section= 的路由跳转） */
export function dispatchStrategySetSection(section: string) {
    if (typeof window !== "undefined" && window.location.pathname.startsWith("/strategy")) {
        window.dispatchEvent(new CustomEvent(STRATEGY_SET_SECTION_EVENT, { detail: section }))
    }
}
