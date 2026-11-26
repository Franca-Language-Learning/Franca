// The app's root: data fetching (TanStack Query) and routes (TanStack Router).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createBrowserHistory,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import { useState } from "react";
import { HomePage } from "./features/home";

function NotFound() {
  return (
    <main>
      <h1>Page not found</h1>
      <p>
        There is no page at this address. <Link to="/">Go to the home page</Link>.
      </p>
    </main>
  );
}

const rootRoute = createRootRoute({ component: Outlet, notFoundComponent: NotFound });
const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: HomePage });
const routeTree = rootRoute.addChildren([homeRoute]);

function makeRouter(initialPath?: string) {
  const history = initialPath ? createMemoryHistory({ initialEntries: [initialPath] }) : createBrowserHistory();
  return createRouter({ routeTree, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}

/** initialPath is for tests. In the browser, the path is read from the address bar. */
export function AppRoot({ initialPath }: { initialPath?: string }) {
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: initialPath ? false : 2 } } }));
  const [router] = useState(() => makeRouter(initialPath));
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
