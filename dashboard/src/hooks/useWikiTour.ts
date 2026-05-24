import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface TourPage {
  path: string;
  title: string;
  reading_order: number;
  architecture_layer: string;
}

interface TourStep {
  order: number;
  layer_name: string;
  layer_display: string;
  pages: TourPage[];
}

interface GuidedTourData {
  total_pages: number;
  steps: TourStep[];
}

export function useWikiTour(businessId: string) {
  return useQuery<GuidedTourData>({
    queryKey: ["wiki-tour", businessId],
    queryFn: () => api(`/wiki/tour?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
  });
}
