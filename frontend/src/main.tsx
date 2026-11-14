import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./studio-theme.css";
import "./sidebar.css";
import "./production.css";
import "./history-actions.css";
import "./canvas-studio.css";

createRoot(document.getElementById("root")!).render(<App />);
