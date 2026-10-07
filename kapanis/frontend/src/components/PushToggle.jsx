import { useEffect, useState } from "react";
import { toast } from "sonner";
import { K } from "@/ds";
import api, { formatApiErrorDetail } from "@/lib/api";

// Uygulama bildirimleri (Web Push): botun Telegram'a attığı otomatik mesajlar bu cihaza da gelir.
const supported = () => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function keyBytes(b64) {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

// The service worker, or null when none becomes ready (not registered, blocked): never wait for it forever
const worker = () => Promise.race([navigator.serviceWorker.ready, new Promise((done) => setTimeout(() => done(null), 4000))]);

export default function PushToggle() {
  const [state, setState] = useState("loading");   // loading | unsupported | denied | off | on
  const [busy, setBusy] = useState(false);

  const read = async () => {
    if (!supported()) return setState("unsupported");
    if (Notification.permission === "denied") return setState("denied");
    try {
      const reg = await worker();
      if (!reg) return setState("unsupported");
      setState((await reg.pushManager.getSubscription()) ? "on" : "off");
    } catch { setState("off"); }
  };
  useEffect(() => { read(); }, []);

  const enable = async () => {
    setBusy(true);
    try {
      if ((await Notification.requestPermission()) !== "granted") { setState(Notification.permission === "denied" ? "denied" : "off"); return; }
      const reg = await worker();
      if (!reg) { setState("unsupported"); return; }
      const { data } = await api.get("/push/key");
      const sub = (await reg.pushManager.getSubscription())
        || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(data.key) }));
      await api.post("/push/subscribe", sub.toJSON());
      setState("on");
      toast.success("Bu cihazda uygulama bildirimleri açık.");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Bildirim açılamadı. Tarayıcı izinlerini kontrol et.");
    } finally { setBusy(false); }
  };

  const disable = async () => {
    setBusy(true);
    try {
      const reg = await worker();
      const sub = reg && (await reg.pushManager.getSubscription());
      if (sub) {
        await api.post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
        await sub.unsubscribe();
      }
      setState("off");
      toast.success("Bu cihazda uygulama bildirimleri kapatıldı.");
    } finally { setBusy(false); }
  };

  const test = async () => {
    try { await api.post("/push/test"); toast.success("Test bildirimi gönderildi."); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Gönderilemedi."); }
  };

  return (
    <K.Card title="Uygulama bildirimleri">
      <p className="m-0 text-t-2">Botun Telegram'a attığı otomatik mesajlar (alarm, seviye özeti, çıkış uyarısı) bu cihaza da bildirim olarak gelir.
        Telegram bildirimleri aynen sürer. Her cihazda ayrı açılır.</p>
      <div className="mt-4 flex flex-wrap items-center gap-3" data-testid="push-toggle" data-state={state}>
        {state === "loading" && <span className="kp-note m-0">Kontrol ediliyor…</span>}
        {state === "unsupported" && <span className="kp-note m-0">Bu tarayıcı uygulama bildirimini desteklemiyor. Android'de Kapanış uygulaması ya da Chrome kullan.</span>}
        {state === "denied" && <span className="kp-note m-0">Bildirim izni bu cihazda engellenmiş. Telefon ayarları → Uygulamalar → Kapanış (ya da Chrome) → Bildirimler'den izin ver.</span>}
        {state === "off" && <K.Button variant="primary" onClick={enable} disabled={busy}>{busy ? "Açılıyor…" : "Bu cihazda aç"}</K.Button>}
        {state === "on" && <>
          <span className="kp-alarm__status is-up">Açık</span>
          <K.Button variant="secondary" onClick={test}>Test bildirimi gönder</K.Button>
          <K.Button variant="ghost" onClick={disable} disabled={busy}>Kapat</K.Button>
        </>}
      </div>
      <p className="kp-note">Hangi piyasadan bildirim geleceğini Telegram'da /bildirimler ile ya da Ayarlar'dan seçersin; kapalı piyasa buraya da gelmez.</p>
    </K.Card>
  );
}
