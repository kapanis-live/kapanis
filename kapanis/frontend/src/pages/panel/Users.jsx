import { K } from "@/ds";
import { useData } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { relDay } from "@/lib/dsmap";
import { useLang } from "@/lib/i18n";

// Yalnız sistem sahibi: kim kayıt oldu, ne kadar analiz istiyor. Portföy içerikleri gösterilmez.
export default function Users() {
  const { t } = useLang();
  const q = useData("admin-users", "/admin/users", { refetchInterval: 60_000 });
  return (
    <DataView query={q} loadingText={t("Kullanıcılar yükleniyor...")}>
      {(d) => {
        const users = d.kullanicilar || [];
        const others = users.filter((u) => u.rol === "user");
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title={t("Kullanıcılar")} subtitle={t("Kayıt olanlar ve kullanım. Portföy içerikleri burada görünmez.")} />
            <div className="kp-grid kp-g-4">
              <K.StatCard label={t("Kullanıcı")} value={String(others.length)} sub={t("{n} hesap (sen dahil)", { n: users.length })} />
              <K.StatCard label={t("Telegram bağlı")} value={String(others.filter((u) => u.telegram).length)} />
              <K.StatCard label={t("Kendi API anahtarı olan")} value={String(others.filter((u) => u.kendi_anahtari?.length).length)} />
              <K.StatCard label={t("Son 24 saat analiz")} value={String(d.kullanici_analiz_24s ?? 0)} sub={t("kullanıcıların toplamı")} />
            </div>
            <K.Card title={t("Hesaplar")}>
              {!users.length ? <EmptyState text={t("Henüz hesap yok.")} /> : (
                <K.DataTable rows={users} rowKey="email" columns={[
                  { key: "email", label: t("E-posta"), render: (u) => <span className="break-all font-semibold text-t-1">{u.email}</span> },
                  { key: "rol", label: t("Rol"), render: (u) => (u.rol === "user" ? t("Kullanıcı") : t("Sahip")) },
                  { key: "kayit", label: t("Kayıt"), mobile: false, render: (u) => (u.kayit ? relDay(u.kayit) : "—") },
                  { key: "giris", label: t("Giriş§oturum"), mobile: false },
                  { key: "telegram", label: "Telegram", render: (u) => (u.telegram ? t("bağlı") : "—") },
                  { key: "kendi_anahtari", label: t("Kendi anahtarı"), mobile: false, render: (u) => u.kendi_anahtari?.join(", ") || "—" },
                  { key: "acik_pozisyon", label: t("Açık poz."), num: true },
                  { key: "analiz_24s", label: t("Analiz (24 sa)"), num: true, strong: true },
                  { key: "analiz_toplam", label: t("Toplam"), num: true, mobile: false },
                ]} />
              )}
              <p className="kp-note">{t("Sınırlar: kendi anahtarı olmayan kullanıcı günde USER_DAILY_ANALYSES, olan USER_KEY_DAILY_ANALYSES; ortak (senin ödediğin) kapasite GLOBAL_DAILY_ANALYSES.")}</p>
            </K.Card>
          </div>
        );
      }}
    </DataView>
  );
}
