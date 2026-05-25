import type { DefaultOptions } from "@tanstack/react-query";
import { STALE_TIME } from "./cacheConfig";
import { getErrorMessage } from "../utils/errorUtils";
import { showGlobalToast } from "../components/Toast";

export const GC_TIME = 300_000;

export const appQueryClientDefaultOptions: DefaultOptions = {
  queries: {
    retry: 1,
    refetchOnWindowFocus: false,
    staleTime: STALE_TIME.FAST,
    gcTime: GC_TIME,
  },
  mutations: {
    onError: (err) => {
      console.error("Mutation error:", err);
      const message = getErrorMessage(err, "Request failed");
      showGlobalToast("error", message);
    },
  },
};
