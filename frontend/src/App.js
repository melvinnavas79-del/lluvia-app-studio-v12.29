import "@/App.css";
import { useState } from "react";
import { AuthProvider, useAuth } from "./AuthContext";
import { BrandingProvider, useBranding } from "./BrandingContext";
import { ThemeProvider } from "./ThemeContext";
import Login from "./components/Login";
import AdminDashboard from "./components/AdminDashboard";
import ClientDashboard from "./components/ClientDashboard";
import PublicChat from "./components/PublicChat";
import { SkeletonAppShell } from "./components/SkeletonLoader";

function Inner() {
  const { user, checking } = useAuth();
  const { branding } = useBranding();
  const [authView, setAuthView] = useState(null); // null | "login" | "register"

  if (checking) {
    return <SkeletonAppShell brandName={branding?.product_name || "Lluvia"} />;
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
      <ThemeProvider>
        <BrandingProvider>
          <AuthProvider>
            <Inner />
          </AuthProvider>
        </BrandingProvider>
      </ThemeProvider>
    </div>
  );
}
