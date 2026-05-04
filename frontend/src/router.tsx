/**
 * TanStack Router v1 — code-based route tree.
 */

import { createRouter } from "@tanstack/react-router";
import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes/index";
import { configsRoute } from "./routes/configs";
import { configEditorRoute } from "./routes/configs.$filename";
import { runsRoute } from "./routes/runs";
import { scheduleRoute } from "./routes/schedule";
import { artifactsRoute } from "./routes/artifacts";
import { contactosRoute } from "./routes/contactos";

const routeTree = rootRoute.addChildren([
  indexRoute,
  configsRoute,
  configEditorRoute,
  runsRoute,
  scheduleRoute,
  artifactsRoute,
  contactosRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  basepath: "/app",
});

// Register the router instance for type safety
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
