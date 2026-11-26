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
import { PasskeysPage } from "./features/passkeys";
import { RecoveryCodeSignInPage, RecoveryCodesPage } from "./features/recovery-codes";
import { SignInPage } from "./features/sign-in";

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
const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sign-in",
  validateSearch: (search: Record<string, unknown>): { error?: string } =>
    typeof search.error === "string" ? { error: search.error } : {},
  component: function SignInRouteComponent() {
    return <SignInPage error={signInRoute.useSearch().error} />;
  },
});
const passkeysRoute = createRoute({ getParentRoute: () => rootRoute, path: "/passkeys", component: PasskeysPage });
const recoveryCodesRoute = createRoute({ getParentRoute: () => rootRoute, path: "/recovery-codes", component: RecoveryCodesPage });
const recoverySignInRoute = createRoute({ getParentRoute: () => rootRoute, path: "/sign-in/recovery-code", component: RecoveryCodeSignInPage });
const routeTree = rootRoute.addChildren([homeRoute, signInRoute, passkeysRoute, recoveryCodesRoute, recoverySignInRoute]);

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
