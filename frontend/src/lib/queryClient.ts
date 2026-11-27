import { QueryClient } from "@tanstack/react-query";

export const queryKeys = {
  waiting: ["waiting"] as const,
  recentRuns: ["runs", "recent"] as const,
};

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        staleTime: 0,
      },
    },
  });
}
