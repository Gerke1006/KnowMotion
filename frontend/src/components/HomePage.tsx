import { useEffect, useState, type MouseEvent } from "react";
import {
  ArrowDown,
  ArrowRight,
  AudioLines,
  Check,
  CheckCheck,
  ChevronRight,
  Clapperboard,
  FileText,
  Film,
  Layers3,
  MoveUpRight,
  Sparkles,
  Workflow,
} from "lucide-react";
import { Brand } from "./Brand";
import { showcaseWorks } from "../showcase";
import "../home.css";

export default function HomePage({ onStart }: { onStart: () => void }) {
  const [selectedId, setSelectedId] = useState(showcaseWorks[0].id);
  const [mediaError, setMediaError] = useState(false);
  const selected = showcaseWorks.find((work) => work.id === selectedId)!;

  useEffect(() => setMediaError(false), [selected.id, selected.videoUrl]);

  const start = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onStart();
  };

  return (
    <div className="home-page" id="home-top">
      <a className="skip-link" href="#home-content">跳到主内容</a>
      <header className="home-header">
        <div className="home-header-inner">
          <a className="home-brand" href="#home-top" aria-label="KnowMotion 知动首页"><Brand /></a>
          <nav className="home-nav" aria-label="首页导航">
            <a href="#showcase">作品展示</a>
            <a href="#how-it-works">制作流程</a>
            <a href="#home-features">产品特点</a>
          </nav>
          <a className="home-button home-button-primary home-header-cta" href="/workspace" onClick={start}>
            生成新的视频<ArrowRight size={16} />
          </a>
        </div>
      </header>

      <main id="home-content" tabIndex={-1}>
        <section className="home-hero" aria-labelledby="home-title">
          <div className="home-kicker"><span />让知识被看见，让理解更自然</div>
          <h1 id="home-title">把知识点<br />转化为<span className="home-title-accent">动画<svg viewBox="0 0 240 14" aria-hidden="true"><path d="M4 10C66 2 166 1 236 7" /></svg></span></h1>
          <p className="home-hero-copy">从一个知识点出发，自动完成讲解、分镜、配音与动画。<br className="home-desktop-break" />把抽象的概念，变成看得懂的画面。</p>
          <div className="home-hero-actions">
            <a className="home-button home-button-primary" href="/workspace" onClick={start}>开始创作<ArrowRight size={18} /></a>
            <a className="home-browse-link" href="#showcase">浏览作品<ArrowDown size={16} /></a>
          </div>
          <div className="home-hero-note"><Check size={13} />从知识点到完整视频，在一个工作台完成</div>
        </section>

        <section id="showcase" className="home-showcase home-container" aria-labelledby="showcase-title">
          <div className="home-section-topline">
            <h2 id="showcase-title"><span className="home-section-dot" />知识，可以这样讲</h2>
            <span>从一个概念，看见一种新的表达</span>
          </div>
          <div className="home-featured-work">
            <div className="home-work-visual">
              {selected.videoUrl && !mediaError ? (
                <video
                  key={selected.id}
                  controls
                  playsInline
                  preload="metadata"
                  src={selected.videoUrl}
                  poster={selected.poster}
                  aria-label={selected.title}
                  onError={() => setMediaError(true)}
                />
              ) : (
                <>
                  <img src={selected.poster} alt={`${selected.title}，知识图解封面`} fetchPriority="high" />
                  <span className="home-pending-video"><Film size={15} />视频暂时无法播放</span>
                </>
              )}
            </div>
            <div className="home-featured-caption" aria-live="polite">
              <div><span className="home-work-category">{selected.category}</span><h3>{selected.title}</h3></div>
              <p>{selected.description}</p>
            </div>
          </div>
          <div className="home-work-options" role="group" aria-label="选择展示作品">
            {showcaseWorks.map((work, index) => (
              <button
                key={work.id}
                className={`home-work-option ${selectedId === work.id ? "is-selected" : ""}`}
                type="button"
                aria-pressed={selectedId === work.id}
                aria-label={`预览${work.title}`}
                onClick={() => setSelectedId(work.id)}
              >
                <div className="home-work-thumb"><img src={work.poster} alt="" loading="lazy" /><span className="home-work-number">{String(index + 1).padStart(2, "0")}</span>{selectedId === work.id && <span className="home-work-selected"><Check size={13} /></span>}</div>
                <div className="home-work-option-copy"><span>{work.category}</span><strong>{work.title}</strong></div>
              </button>
            ))}
          </div>
          <p className="home-showcase-note">选择作品，即可播放完整示例视频。</p>
        </section>

        <section className="home-workflow-section" id="how-it-works" aria-labelledby="workflow-title">
          <div className="home-container">
            <div className="home-section-heading"><span className="home-eyebrow">从想法，到画面</span><h2 id="workflow-title">把复杂留给我们，<br />把灵感留给你。</h2><p>不用从空白时间轴开始，一段清晰的描述就足够。</p></div>
            <ol className="home-workflow">
              <li><div className="home-step-top"><span>01</span><FileText size={25} strokeWidth={1.5} /><ChevronRight className="home-step-arrow" size={20} /></div><h3>描述知识点</h3><p>告诉我们你想讲什么，<br />也可以补充想让观众理解的重点。</p><div className="home-step-note">“为什么导数表示瞬时变化率？”</div></li>
              <li><div className="home-step-top"><span>02</span><Workflow size={25} strokeWidth={1.5} /><ChevronRight className="home-step-arrow" size={20} /></div><h3>智能编排与制作</h3><p>梳理知识、组织讲解、设计分镜，<br />让画面、字幕与配音一起成形。</p><div className="home-step-note"><Sparkles size={14} />每一个制作阶段，清晰可见</div></li>
              <li><div className="home-step-top"><span>03</span><Clapperboard size={25} strokeWidth={1.5} /></div><h3>观看与下载</h3><p>在工作台查看完整视频，<br />下载保存，或随时回到视频库重温。</p><div className="home-step-note"><CheckCheck size={14} />作品与创作记录，集中管理</div></li>
            </ol>
          </div>
        </section>

        <section id="home-features" className="home-features home-container" aria-labelledby="features-title">
          <div className="home-feature-intro"><div><span className="home-eyebrow">为理解而创作</span><h2 id="features-title">让知识动起来，<br />也让理解更进一步。</h2></div><p>从数学推导到历史叙事，<br />让内容决定表达，让画面帮助理解。</p></div>
          <div className="home-feature-grid">
            <article className="home-feature">
              <div className="home-feature-drawing home-abstract-drawing" aria-hidden="true"><svg viewBox="0 0 320 160"><path d="M32 130H285M55 144V20" stroke="#CBD8D2" strokeWidth="1.5" /><path d="M58 124C118 124 142 110 178 75C207 46 236 38 275 28" stroke="#2B7A78" strokeWidth="3" fill="none" /><path d="M140 124L236 34" stroke="#142D43" strokeWidth="2" /><circle cx="182" cy="85" r="14" fill="#2B7A78" fillOpacity=".12" /><circle cx="182" cy="85" r="4" fill="#2B7A78" /></svg><span>从抽象，到直观</span></div>
              <div className="home-feature-icon"><Layers3 size={20} /></div><h3>让抽象概念，看得见</h3><p>用曲线表达变化，用几何解释关系。把文字中的逻辑，转化为画面中的线索。</p>
            </article>
            <article className="home-feature">
              <div className="home-feature-drawing home-sync-drawing" aria-hidden="true"><div className="home-audio-wave">{[12, 23, 34, 19, 40, 55, 35, 62, 46, 26, 48, 35, 18, 30, 15].map((height, index) => <i key={index} style={{ height }} />)}</div><div className="home-subtitle-strip">声音与画面，讲述同一个知识点</div><span>一段讲解，一份完整表达</span></div>
              <div className="home-feature-icon"><AudioLines size={20} /></div><h3>讲到哪里，看到哪里</h3><p>让配音、字幕与动画围绕同一段讲解展开。听见知识的同时，也看见它如何发生。</p>
            </article>
            <article className="home-feature">
              <div className="home-feature-drawing home-progress-drawing" aria-hidden="true"><div><span><Check size={12} />讲稿</span><i /><span><Check size={12} />分镜</span><i /><span><Check size={12} />成片</span></div><div className="home-static-progress"><i /></div><span>从第一步，到完整成片</span></div>
              <div className="home-feature-icon"><Workflow size={20} /></div><h3>创作进度，心中有数</h3><p>查看每个阶段的制作状态。完成后统一播放、下载，在历史记录中找回每一次创作。</p>
            </article>
          </div>
        </section>

        <section className="home-closing home-container" aria-labelledby="closing-title">
          <div className="home-closing-art" aria-hidden="true"><span /><span /><span /></div>
          <div><span className="home-eyebrow">你的下一个知识点，值得被看见</span><h2 id="closing-title">让一个好想法，<br />成为一段好讲解。</h2><p>从现在开始，把你理解的世界，讲给更多人。</p></div>
          <a className="home-button home-button-light" href="/workspace" onClick={start}>开始创作<MoveUpRight size={18} /></a>
        </section>
      </main>

      <footer className="home-footer home-container"><div><a href="#home-top" aria-label="KnowMotion 返回顶部"><Brand /></a><p>知动 · 让知识有形，让理解发生。</p></div><a href="/workspace" onClick={start}>进入工作台<ArrowRight size={15} /></a></footer>
    </div>
  );
}
