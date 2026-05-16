import "@/App.css";
import { useState } from "react";
import { AuthProvider, useAuth } from "./AuthContext";
import { BrandingProvider } from "./BrandingContext";
import Login from "./components/Login";
import AdminDashboard from "./components/AdminDashboard";
import AffiliateDashboard from "./components/AffiliateDashboard";
import PublicChat from "./components/PublicChat";

function Inner() {
  const { user, checking } = useAuth();
  const [showLogin, setShowLogin] = useState(false);

  if (checking) {
    return (
      <div className="login-wrap">
        <div className="login-card" style={{ textAlign: "center" }}>
          <div className="brand-mark" style={{ justifyContent: "center" }}>
            <span className="brand-dot" />
            <span>CARGANDO...</span>
          </div>
        </div>
      </div>
    );
  }

  if (!user) {
    return showLogin ? <Login onBack={() => setShowLogin(false)} /> : <PublicChat onAdminClick={() => setShowLogin(true)} />;
  }
  if (user.role === "admin") return <AdminDashboard />;
  return <AffiliateDashboard />;
}

export default function App() {
  return (
    <div className="App">
      <BrandingProvider>
        <AuthProvider>
          <Inner />
        </AuthProvider>
      </BrandingProvider>
    </div>
  );
}
