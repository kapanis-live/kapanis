import { useEffect, useState } from "react";
import { K } from "@/ds";
import { API } from "@/lib/api";
import { useLang } from "@/lib/i18n";

// İletişim: yalnız gerçekten çalışan kanallar (sunucu ayarındaki CONTACT_EMAIL ve Telegram botu).
// Mesaj gönderen bir form yok; sahte "mesajın alındı" göstermiyoruz.
export default function Iletisim() {
  const { t } = useLang();
  const [cfg, setCfg] = useState(null);
  useEffect(() => {
    fetch(`${API}/auth/config`).then((r) => r.json()).then(setCfg).catch(() => setCfg({}));
  }, []);
  const mail = cfg?.iletisim;
  const bot = cfg?.telegram_bot;
  return (
    <section className="kp-sec">
      <div className="kp-sec__head">
        <div className="kp-sec__kicker">{t("İletişim")}</div>
        <h1 className="kp-hero__title" style={{ fontSize: "2.75rem" }}>{t("Bize ulaş")}</h1>
        <p className="kp-sec__lead">{t("Soru, hata bildirimi ya da veri talebi (KVKK) için yaz. Yatırım danışmanlığı vermiyoruz.")}</p>
      </div>
      <div className="kp-grid kp-g-2" style={{ maxWidth: "52rem" }}>
        <K.FeatureCard icon="send" title={t("E-posta")}>
          {cfg === null ? "…" : mail ? <a className="kp-link" href={`mailto:${mail}`}>{mail}</a> : t("E-posta adresi henüz eklenmedi.")}
        </K.FeatureCard>
        <K.FeatureCard icon="send" title={t("Telegram botu")}>
          {cfg === null ? "…" : bot ? <a className="kp-link" href={`https://t.me/${bot}`} target="_blank" rel="noreferrer">@{bot}</a> : t("Bot adı henüz eklenmedi.")}
          {" "}{t("Botta yalnız hesabını bağlayabilirsin (/bagla); destek mesajlarını e-postayla gönder.")}
        </K.FeatureCard>
      </div>
      <p className="kp-note" style={{ marginTop: "1.5rem" }}>{t("Kapanış bir karar destek aracıdır: kişiye özel yatırım tavsiyesi, portföy yönetimi ya da getiri garantisi sunmaz.")}</p>
    </section>
  );
}
