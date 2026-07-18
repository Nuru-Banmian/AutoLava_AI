import { QueryClient } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Application } from "./App";
import { createAppRouter } from "./router";
import "./index.css";
import "leaflet/dist/leaflet.css";

const queryClient = new QueryClient();
const router = createAppRouter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Application queryClient={queryClient} router={router} />
  </StrictMode>,
);
