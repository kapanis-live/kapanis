// Anlık güncelleme: sunucunun "portföyün değişti" olayını (yalnız sürüm numarası) dinler.
// EventSource başlık gönderemediği için fetch akışı kullanılır; Clerk oturum jetonu başlıkta gider.
import { useEffect, useRef } from "react";
import { API } from "@/lib/api";

let tokenGetter = async () => null;
export function setLiveTokenGetter(fn) {
  tokenGetter = fn || (async () => null);
}

export function usePortfolioStream(onRevision, enabled = true) {
  const cb = useRef(onRevision);
  cb.current = onRevision;
  useEffect(() => {
    if (!enabled) return undefined;
    let stopped = false;
    let ctrl = null;
    let wait = 1000;
    const loop = async () => {
      while (!stopped) {
        ctrl = new AbortController();
        try {
          const token = await tokenGetter();
          const res = await fetch(`${API}/portfolio/stream`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: "include", signal: ctrl.signal,
          });
          if (!res.ok || !res.body) throw new Error(String(res.status));
          wait = 1000;
          const reader = res.body.getReader();
          const dec = new TextDecoder();
          let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            let i;
            while ((i = buf.indexOf("\n\n")) >= 0) {
              const block = buf.slice(0, i);
              buf = buf.slice(i + 2);
              const m = block.match(/^event: rev\ndata: (\d+)/);
              if (m) cb.current(Number(m[1]));
            }
          }
        } catch (e) {
          if (stopped) return;
          wait = Math.min(wait * 2, 30000); // bağlantı koparsa artan aralıkla yeniden dene; 8 sn'lik yenileme zaten sürüyor
        }
        if (!stopped) await new Promise((r) => setTimeout(r, wait));
      }
    };
    loop();
    return () => {
      stopped = true;
      ctrl?.abort();
    };
  }, [enabled]);
}
