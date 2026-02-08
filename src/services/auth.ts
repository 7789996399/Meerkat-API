import * as msal from "@azure/msal-node";
import jwt from "jsonwebtoken";
import prisma from "../lib/prisma";

// --- MSAL Configuration ---

let _msalClient: msal.ConfidentialClientApplication | null = null;

function getMsalClient(): msal.ConfidentialClientApplication {
  if (!_msalClient) {
    const clientId = process.env.MICROSOFT_CLIENT_ID;
    const clientSecret = process.env.MICROSOFT_CLIENT_SECRET;
    const tenantId = process.env.MICROSOFT_TENANT_ID;

    if (!clientId || !clientSecret || !tenantId) {
      throw new Error(
        "MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, and MICROSOFT_TENANT_ID must be set"
      );
    }

    _msalClient = new msal.ConfidentialClientApplication({
      auth: {
        clientId,
        clientSecret,
        authority: `https://login.microsoftonline.com/${tenantId}`,
      },
    });
  }
  return _msalClient;
}

function getJwtSecret(): string {
  const secret = process.env.JWT_SECRET;
  if (!secret) {
    throw new Error("JWT_SECRET environment variable is not set");
  }
  return secret;
}

function getRedirectUri(): string {
  return process.env.MICROSOFT_REDIRECT_URI || "http://localhost:3000/auth/microsoft/callback";
}

// --- Auth URL ---

export async function getAuthUrl(): Promise<string> {
  const response = await getMsalClient().getAuthCodeUrl({
    scopes: ["openid", "profile", "email"],
    redirectUri: getRedirectUri(),
  });
  return response;
}

// --- Handle Callback ---

export interface AuthResult {
  token: string;
  user: {
    id: string;
    email: string;
    name: string;
    role: string;
    orgId: string;
    orgName: string;
  };
}

export async function handleCallback(code: string): Promise<AuthResult> {
  const tokenResponse = await getMsalClient().acquireTokenByCode({
    code,
    scopes: ["openid", "profile", "email"],
    redirectUri: getRedirectUri(),
  });

  const oid = tokenResponse.uniqueId;
  const email =
    (tokenResponse.idTokenClaims as Record<string, any>)?.preferred_username ||
    (tokenResponse.idTokenClaims as Record<string, any>)?.email ||
    tokenResponse.account?.username ||
    "";
  const name =
    (tokenResponse.idTokenClaims as Record<string, any>)?.name ||
    tokenResponse.account?.name ||
    email;

  if (!oid) {
    throw new Error("Microsoft authentication did not return a user identifier");
  }

  // Find or create user
  let user = await prisma.user.findUnique({
    where: { microsoftOid: oid },
    include: { org: true },
  });

  if (!user) {
    // Auto-provision: create a new org for the user or find by email domain
    const emailDomain = email.split("@")[1];
    let org = null;

    if (emailDomain) {
      // Look for an existing org with users from the same email domain
      const existingUser = await prisma.user.findFirst({
        where: { email: { endsWith: `@${emailDomain}` } },
        include: { org: true },
      });
      if (existingUser) {
        org = existingUser.org;
      }
    }

    if (!org) {
      // Create a new org for this user
      org = await prisma.organization.create({
        data: {
          name: emailDomain ? `${emailDomain} Organization` : `${name}'s Organization`,
          plan: "starter",
          domain: "legal",
        },
      });
    }

    user = await prisma.user.create({
      data: {
        orgId: org.id,
        microsoftOid: oid,
        email,
        name,
        role: "admin",
        lastLoginAt: new Date(),
      },
      include: { org: true },
    });

    console.log(`[auth] New user created: ${email} (org: ${user.org.name})`);
  } else {
    // Update last login
    await prisma.user.update({
      where: { id: user.id },
      data: { lastLoginAt: new Date() },
    });
  }

  // Generate JWT session token
  const token = jwt.sign(
    {
      sub: user.id,
      orgId: user.orgId,
      email: user.email,
      name: user.name,
      role: user.role,
    },
    getJwtSecret(),
    { expiresIn: "8h" }
  );

  return {
    token,
    user: {
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
      orgId: user.orgId,
      orgName: user.org.name,
    },
  };
}

// --- JWT Validation ---

export interface JwtPayload {
  sub: string;
  orgId: string;
  email: string;
  name: string;
  role: string;
}

export function verifyToken(token: string): JwtPayload {
  return jwt.verify(token, getJwtSecret()) as JwtPayload;
}
