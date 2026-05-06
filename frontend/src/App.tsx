import { useEffect, useState } from "react";
import { clearToken, fetchMe, getStoredToken, storeToken, type User } from "./api";
import { Dashboard } from "./Dashboard";
import { LoginPage } from "./LoginPage";

type AuthState =
  | { status: "loading"; token: string | null; user: null }
  | { status: "anonymous"; token: null; user: null }
  | { status: "authenticated"; token: string; user: User };

export function App() {
  const [auth, setAuth] = useState<AuthState>({ status: "loading", token: null, user: null });

  useEffect(() => {
    const token = getStoredToken();
    if (!token) {
      setAuth({ status: "anonymous", token: null, user: null });
      return;
    }
    fetchMe(token)
      .then((user) => setAuth({ status: "authenticated", token, user }))
      .catch(() => {
        clearToken();
        setAuth({ status: "anonymous", token: null, user: null });
      });
  }, []);

  if (auth.status === "loading") {
    return <div className="boot-screen">Loading...</div>;
  }

  if (auth.status === "anonymous") {
    return (
      <LoginPage
        onAuthenticated={(token, user) => {
          storeToken(token);
          setAuth({ status: "authenticated", token, user });
        }}
      />
    );
  }

  return (
    <Dashboard
      token={auth.token}
      user={auth.user}
      onLogout={() => {
        clearToken();
        setAuth({ status: "anonymous", token: null, user: null });
      }}
    />
  );
}
