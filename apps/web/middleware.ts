import { auth } from "@/auth";

export default auth((req) => {
  if (process.env.AUTH_DISABLED === "1") return;
  if (!req.auth) {
    const url = new URL("/api/auth/signin", req.nextUrl.origin);
    url.searchParams.set("callbackUrl", req.nextUrl.href);
    return Response.redirect(url);
  }
});

export const config = {
  // everything except auth endpoints and static assets
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"],
};
