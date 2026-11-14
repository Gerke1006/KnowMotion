import { useEffect, useState } from "react";
import HomePage from "./components/HomePage";
import Workspace from "./Workspace";

function readPage(): "home" | "workspace" {
  const url = new URL(window.location.href);
  const legacy = url.pathname === "/" &&
    (Boolean(url.searchParams.get("job")) || ["library", "history", "new"].includes(url.searchParams.get("view") || ""));
  if (legacy) {
    url.pathname = "/workspace";
    history.replaceState(null, "", url);
  }
  return url.pathname.replace(/\/$/, "") === "/workspace" ? "workspace" : "home";
}

export default function App() {
  const [page, setPage] = useState(readPage);
  // Credentials stay only in this tab's memory, including page transitions.
  const [token, setToken] = useState("");

  useEffect(() => {
    const onPop = () => setPage(readPage());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    document.title = page === "home"
      ? "KnowMotion 知动 · 把知识点转化为动画"
      : "KnowMotion · 知动工作台";
    window.scrollTo({ top: 0, behavior: "instant" });
    const frame = requestAnimationFrame(() => {
      document.getElementById(page === "workspace" ? "main-content" : "home-content")?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [page]);

  function navigate(next: "home" | "workspace") {
    history.pushState(null, "", next === "home" ? "/" : "/workspace");
    setPage(next);
  }

  return page === "home"
    ? <HomePage onStart={() => navigate("workspace")} />
    : <Workspace token={token} onTokenChange={setToken} onHome={() => navigate("home")} />;
}
