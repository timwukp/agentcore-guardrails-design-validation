import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

// HashRouter, not BrowserRouter, and the choice is load-bearing rather than a convenience.
//
// A BrowserRouter on S3 + CloudFront needs a custom error response mapping 404 -> /index.html with
// HTTP 200 so that a deep link resolves. That rewrite cannot distinguish "this is an app route" from
// "this file is genuinely missing", so a typo'd or unpublished `data/cases/F9-9.json` would come back
// as 200 text/html — a missing artifact wearing a successful response. In a project whose whole
// discipline is that an absent measurement must look absent, that is the wrong default. With the
// route in the fragment, the origin only ever serves real files, a missing one 404s honestly, and
// lib/data.ts can tell the reader which of the two happened.

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

createRoot(root).render(
  <StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </StrictMode>,
);
