/// <reference types="vite/client" />
import derivative from "./assets/showcase/derivative.svg";
import geometry from "./assets/showcase/geometry.svg";
import probability from "./assets/showcase/probability.svg";
import history from "./assets/showcase/history.svg";
import derivativeVideo from "./assets/showcase/derivative.mp4?url";
import geometryVideo from "./assets/showcase/geometry.mp4?url";
import probabilityVideo from "./assets/showcase/probability.mp4?url";
import historyVideo from "./assets/showcase/history.mp4?url";

export type ShowcaseWork = {
  id: string;
  title: string;
  category: string;
  description: string;
  poster: string;
  videoUrl: string;
};

// 首页独立展示资源随前端构建发布，播放示例不会创建后台任务。
export const showcaseWorks: ShowcaseWork[] = [
  {
    id: "derivative",
    title: "导数：看见变化的瞬间",
    category: "数学 · 微积分",
    description: "让一条割线慢慢靠近切线，看懂瞬时变化率从何而来。",
    poster: derivative,
    videoUrl: derivativeVideo,
  },
  {
    id: "geometry",
    title: "勾股定理：藏在面积里的答案",
    category: "数学 · 几何",
    description: "从三个正方形出发，用形状与面积理解直角三角形的秘密。",
    poster: geometry,
    videoUrl: geometryVideo,
  },
  {
    id: "probability",
    title: "概率：在随机中寻找规律",
    category: "数学 · 概率",
    description: "从一次掷骰到许多次试验，把抽象的概率变成直观的分布。",
    poster: probability,
    videoUrl: probabilityVideo,
  },
  {
    id: "history",
    title: "张骞：一条路如何连接世界",
    category: "历史 · 丝绸之路",
    description: "跟随地图上的足迹，理解张骞出使西域的来龙去脉。",
    poster: history,
    videoUrl: historyVideo,
  },
];
