import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export function useData(key, path, options = {}) {
  return useQuery({
    queryKey: Array.isArray(key) ? key : [key],
    queryFn: async () => {
      const { data } = await api.get(path);
      return data;
    },
    ...options,
  });
}

// Bekleyen bot komutlarını periyodik olarak izler.
// Bir komut tamamlanınca (bot "done" işaretleyip veriyi ingest edince)
// listeden düşer ve ilgili "bota iletildi" rozeti kendiliğinden kalkar.
export function usePendingCommands() {
  const q = useQuery({
    queryKey: ["commands"],
    queryFn: async () => {
      const { data } = await api.get("/commands");
      return data;
    },
    refetchInterval: 6000,
    refetchOnWindowFocus: true,
  });
  const pending = (q.data || []).filter((c) => c.status === "pending");
  const has = (type, id) => pending.some((c) => c.type === type && c.payload?.id === id);
  return { ...q, pending, has };
}

// Panel veri sorguları için ortak canlı yenileme aralığı.
export const LIVE = { refetchInterval: 8000, refetchOnWindowFocus: true };
