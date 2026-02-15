from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import requests
from app.core.config import settings
from app.core import database
from sqlalchemy import text
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

class AuthCodeRequest(BaseModel):
    code: str
    redirect_uri: str

@router.post("/exchange")
async def exchange_token(data: AuthCodeRequest):
    """
    Exchanges authorization code for access and refresh tokens (Confidential Client Flow).
    """
    try:
        if not data.code:
            raise HTTPException(status_code=400, detail="Missing authorization code")

        # 1. Exchange Code
        token_url = f"https://login.microsoftonline.com/{settings.azure_tenant_id}/oauth2/v2.0/token"
        
        payload = {
            "client_id": settings.azure_client_id,
            "client_secret": settings.azure_client_secret, # REQUIRED for 90-day token
            "grant_type": "authorization_code",
            "code": data.code,
            "redirect_uri": data.redirect_uri,
            "scope": "offline_access https://graph.microsoft.com/.default"
        }
        
        print(f"Exchanging code for tokens. Client ID: {settings.azure_client_id}")
        
        response = requests.post(token_url, data=payload)
        
        if response.status_code != 200:
            print(f"Token exchange failed: {response.text}")
            raise HTTPException(status_code=401, detail=f"Failed to exchange token: {response.text}")
            
        tokens = response.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        
        if not access_token:
             raise HTTPException(status_code=401, detail="No access token received")

        # 2. Get User Email
        user_resp = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if user_resp.status_code != 200:
             raise HTTPException(status_code=401, detail="Failed to fetch user profile")
             
        user_data = user_resp.json()
        email = user_data.get("mail") or user_data.get("userPrincipalName")
        
        if not email:
            raise HTTPException(status_code=400, detail="Could not determine user email")
            
        print(f"Authenticated user: {email}")

        # 3. Save to Database
        if database.SessionLocal:
            session = database.SessionLocal()
            try:
                # Check for existing token
                check_sql = text("SELECT TokenID FROM [Dev_ExpenseApp].[product].[MicrosoftTokens] WHERE Email = :email")
                result = session.execute(check_sql, {"email": email}).fetchone()
                
                now = datetime.utcnow()
                expires_at = now + timedelta(seconds=expires_in)
                
                if result:
                    # Update
                    update_sql = text("""
                        UPDATE [Dev_ExpenseApp].[product].[MicrosoftTokens]
                        SET AccessToken = :at, RefreshToken = :rt, ExpiresAt = :exp, UpdatedAt = :now
                        WHERE Email = :email
                    """)
                    session.execute(update_sql, {
                        "at": access_token,
                        "rt": refresh_token,
                        "exp": expires_at,
                        "now": now,
                        "email": email
                    })
                else:
                    # Insert
                    insert_sql = text("""
                        INSERT INTO [Dev_ExpenseApp].[product].[MicrosoftTokens]
                        (Email, AccessToken, RefreshToken, ExpiresAt, CreatedAt, UpdatedAt)
                        VALUES (:email, :at, :rt, :exp, :now, :now)
                    """)
                    session.execute(insert_sql, {
                        "email": email,
                        "at": access_token,
                        "rt": refresh_token,
                        "exp": expires_at,
                        "now": now
                    })
                
                session.commit()
                print("Tokens saved to database successfully.")
                
            except Exception as e:
                session.rollback()
                print(f"Database error: {e}")
                raise HTTPException(status_code=500, detail="Database error saving tokens")
            finally:
                session.close()
        
        return {"message": "Authentication successful", "email": email}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Auth Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
