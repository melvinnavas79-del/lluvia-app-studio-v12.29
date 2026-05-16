import "@/App.css";
import { useState } from "react";
import { AuthProvider, useAuth } from "./AuthContext";
import { BrandingProvider } from "./BrandingContext";
import Login from "./components/Login";
import AdminDashboard from "./components/AdminDashboard";
import ClientDashboard from "./components/ClientDashboard";
import PublicChat from "./components/PublicChat";

function Inner() {
  const { user, checking } = useAuth();
  const [authView, setAuthView] = useState(null); // null | "login" | "register"

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
    if (authView === "login" || authView === "register") {
      return <Login mode={authView} onBack={() => setAuthView(null)} />;
    }
    return (
      <PublicChat
        onLoginClick={() => setAuthView("login")}
        onRegisterClick={() => setAuthView("register")}
      />
    );
  }
  if (user.role === "admin") return <AdminDashboard />;
  return <ClientDashboard />;
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
