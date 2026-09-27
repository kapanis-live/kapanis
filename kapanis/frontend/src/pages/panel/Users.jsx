import { K } from "@/ds";
import { useData } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { relDay } from "@/lib/dsmap";

// Yalnız sistem sahibi: kim kayıt oldu, ne kadar analiz istiyor. Portföy içerikleri gösterilmez.
export default function Users() {
  const q = useData("admin-users", "/admin/users", { refetchInterval: 60_000 });
  return (
    <DataView query={q} loadingText="Kullanıcılar yükleniyor...">
      {(d) => {
        const users = d.kullanicilar || [];
        const others = users.filter((u) => u.rol === "user");
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title="Kullanıcılar" subtitle="Kayıt olanlar ve kullanım. Portföy içerikleri burada görünmez." />
            <div className="kp-grid kp-g-4">
              <K.StatCard label="Kullanıcı" value={String(others.length)} sub={`${users.length} hesap (sen dahil)`} />
              <K.StatCard label="Telegram bağlı" value={String(others.filter((u) => u.telegram).length)} />
              <K.StatCard label="Kendi API anahtarı olan" value={String(others.filter((u) => u.kendi_anahtari?.length).length)} />
              <K.StatCard label="Son 24 saat analiz" value={String(d.kullanici_analiz_24s ?? 0)} sub="kullanıcıların toplamı" />
            </div>
            <K.Card title="Hesaplar">
              {!users.length ? <EmptyState text="Henüz hesap yok." /> : (
                <K.DataTable rows={users} rowKey="email" columns={[
                  { key: "email", label: "E-posta", render: (u) => <span className="break-all font-semibold text-t-1">{u.email}</span> },
                  { key: "rol", label: "Rol", render: (u) => (u.rol === "user" ? "Kullanıcı" : "Sahip") },
                  { key: "kayit", label: "Kayıt", mobile: false, render: (u) => (u.kayit ? relDay(u.kayit) : "—") },
                  { key: "giris", label: "Giriş", mobile: false },
                  { key: "telegram", label: "Telegram", render: (u) => (u.telegram ? "bağlı" : "—") },
                  { key: "kendi_anahtari", label: "Kendi anahtarı", mobile: false, render: (u) => u.kendi_anahtari?.join(", ") || "—" },
                  { key: "acik_pozisyon", label: "Açık poz.", num: true },
                  { key: "analiz_24s", label: "Analiz (24 sa)", num: true, strong: true },
                  { key: "analiz_toplam", label: "Toplam", num: true, mobile: false },
                ]} />
              )}
              <p className="kp-note">Sınırlar: kendi anahtarı olmayan kullanıcı günde USER_DAILY_ANALYSES, olan USER_KEY_DAILY_ANALYSES; ortak (senin ödediğin) kapasite GLOBAL_DAILY_ANALYSES.</p>
            </K.Card>
          </div>
        );
      }}
    </DataView>
  );
}
