import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Fonts (SIL OFL; licences to confirm before Stage 2 — O19). Self-hosted, no external CDN.
import "@fontsource/fredoka/600.css";
import "@fontsource/fredoka/700.css";
import "@fontsource/plus-jakarta-sans/400.css";
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
import "@fontsource/plus-jakarta-sans/800.css";
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/700.css";
import "@fontsource/noto-sans-sc/800.css";
import "./design/tokens.css";
import "./styles/global.css";
import "./design/components.css";
import "./app/shell.css";
import "./i18n";
import { App } from "./app/App";
import { installResearchReporting } from "./app/research";

installResearchReporting();

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
