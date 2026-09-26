// Kapanış tasarım sistemi: değişkenler, stiller ve bileşenler (window.Kapanis).
// İçe aktarma sırası önemli: önce React global olur, sonra paket yüklenir.
import "./react-global";
import "./tokens.css";
import "./bundle.css";
import "./bundle.js";

export const K = window.Kapanis;
export const U = window.Kapanis.util;
