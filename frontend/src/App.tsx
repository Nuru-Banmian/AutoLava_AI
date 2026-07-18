import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { RouterProvider, type RouterProviderProps } from "react-router-dom";

import { createAppRouter } from "@/router";

export function Application({ queryClient, router }: { queryClient: QueryClient; router: RouterProviderProps["router"] }) {
  return <QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>;
}

export default function App() {
  const [queryClient] = useState(() => new QueryClient());
  const [router] = useState(() => createAppRouter());
  return <Application queryClient={queryClient} router={router} />;
}
