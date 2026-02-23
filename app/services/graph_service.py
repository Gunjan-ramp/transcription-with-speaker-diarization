import msal
import requests
import os
import pyodbc
from datetime import datetime, timedelta
from app.core.config import settings
from app.core.database import SessionLocal, EmailLog


class GraphService:
    def __init__(self, user_email=None):
        self.user_email = user_email or settings.target_user_email or settings.sender_email
        if not self.user_email:
            raise ValueError("User email must be provided for Delegated Authentication.")
            
        self.client_id = settings.azure_client_id
        self.client_secret = settings.azure_client_secret
        self.tenant_id = settings.azure_tenant_id
        
        self.db_connection_string = (
            f"DRIVER={{{settings.db_driver}}};"
            f"SERVER={settings.db_server};"
            f"DATABASE={settings.db_name};"
            f"UID={settings.db_user};"
            f"PWD={settings.db_password};"
            "TrustServerCertificate=yes"
        )
        
        self.access_token = None
        self._authenticate()

    def _get_db_connection(self):
        return pyodbc.connect(self.db_connection_string)

    def _authenticate(self):
        """
        Authenticate using tokens stored in the database.
        Refreshes the token if it is expired.
        """
        print(f"Authenticating for {self.user_email} via DB...")
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Fetch token
            # Note: We are accessing [Dev_ExpenseApp].[product].[MicrosoftTokens]
            # Assumes the user has permissions to access this cross-database object
            query = """
            SELECT TOP 1 access_token, refresh_token, expires_at 
            FROM [Dev_ExpenseApp].[product].[MicrosoftTokens] 
            WHERE email_id = ?
            ORDER BY created_at DESC
            """
            cursor.execute(query, (self.user_email,))
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                raise Exception(f"No tokens found in database for {self.user_email}")
            
            access_token = row.access_token
            refresh_token = row.refresh_token
            expires_at = row.expires_at # datetime object
            
            # Check expiration (with 5 minute buffer)
            if expires_at and datetime.now() >= (expires_at - timedelta(minutes=5)):
                print("Token expired or expiring soon. Refreshing...")
                self._refresh_and_update_token(refresh_token)
            else:
                self.access_token = access_token
                print("Using existing valid token from DB.")
                
        except Exception as e:
            print(f"Authentication failed: {e}")
            raise

    def _refresh_and_update_token(self, refresh_token):
        """
        Refresh the access token using the refresh token and update the DB.
        """
        token_endpoint = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default", 
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        
        # Web App (Confidential Client) flow doesn't require Origin header like SPA
        headers = {}
        
        response = requests.post(token_endpoint, data=data, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            new_access_token = result.get("access_token")
            new_refresh_token = result.get("refresh_token") # Might be new, might be same
            expires_in = result.get("expires_in", 3600)
            
            new_expires_at = datetime.now() + timedelta(seconds=int(expires_in))
            
            # Update DB
            self._update_db_token(new_access_token, new_refresh_token, new_expires_at)
            
            self.access_token = new_access_token
            print("Token refreshed and DB updated successfully.")
        else:
            raise Exception(f"Failed to refresh token: {response.text}")

    def _update_db_token(self, access_token, refresh_token, expires_at):
        """Update the latest token record in the DB."""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # We update the existing latest record or insert? 
            # The user said "can update in the table". 
            # Let's update the record for this email that is most recent.
            # OR simpler: Update ALL records for this email? No, that's dangerous.
            # Let's update the specific row we fetched? We didn't get ID.
            # Let's just update the most recently created one.
            
            update_query = """
            UPDATE TOP (1) [Dev_ExpenseApp].[product].[MicrosoftTokens]
            SET access_token = ?, refresh_token = ?, expires_at = ?, updated_at = GETDATE()
            WHERE email_id = ?
            """
            # Note: T-SQL UPDATE TOP (1) logic:
            # We need to target the row. Using a subquery or strict WHERE on the latest one is better.
            # But [id] is distinct. Ideally we should have fetched [id].
            # Let's assume updating based on email is "ok" but risks updating old rows if not careful.
            # Better approach: Fetch ID in _authenticate, store it, use it here.
            # For now, to keep it simple, let's update where email matches.
            
            # Wait, better logic: Update the entry with latest created_at
            cursor.execute("""
                UPDATE [Dev_ExpenseApp].[product].[MicrosoftTokens]
                SET access_token = ?, refresh_token = ?, expires_at = ?, updated_at = GETDATE()
                WHERE id = (SELECT TOP 1 id FROM [Dev_ExpenseApp].[product].[MicrosoftTokens] WHERE email_id = ? ORDER BY created_at DESC)
            """, (access_token, refresh_token, expires_at, self.user_email))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Failed to update token in DB: {e}")
            raise

    def _get_headers(self):
        if not self.access_token:
            self._authenticate()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def list_files_in_folder(self, folder_path):
        """
        List files in a specific folder of the authenticated user's OneDrive.
        Refactored to use /me endpoint.
        """
        # Ensure folder path format
        if not folder_path.startswith("/"):
            folder_path = "/" + folder_path
            
        if folder_path == "/":
            url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
        else:
            url = f"https://graph.microsoft.com/v1.0/me/drive/root:{folder_path}:/children"

        response = requests.get(url, headers=self._get_headers())
        if response.status_code == 200:
            return response.json().get("value", [])
        else:
            print(f"Error listing files: {response.text}")
            # If 401, maybe token expired during execution? 
            # Could implement retry logic calling _authenticate() force=True
            return []

    def download_file(self, file_id, destination_path):
        """Download a file content by ID."""
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/content"
        
        # Stream download
        response = requests.get(url, headers=self._get_headers(), stream=True)
        if response.status_code == 200:
            with open(destination_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        else:
            print(f"Error downloading file {file_id}: {response.text}")
            return False

    def send_email(self, to_email, subject, content, attachment_paths=None):
        """
        Send email using Graph API (/me/sendMail).
        to_email can be a single string or a list of strings.
        """
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
        
        # Handle single vs list of recipients
        if isinstance(to_email, str):
            recipient_list = [to_email]
        else:
            recipient_list = to_email
            
        to_recipients_payload = [
            {
                "emailAddress": {
                    "address": email.strip()
                }
            } for email in recipient_list if email.strip()
        ]
        
        # Construct email message
        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": content
            },
            "toRecipients": to_recipients_payload,
            "attachments": []
        }
        
        if attachment_paths:
            for path in attachment_paths:
                if os.path.exists(path):
                    size = os.path.getsize(path)
                    if size > 3 * 1024 * 1024:
                        print(f"Warning: Attachment {path} is {size} bytes, might fail standard attachment upload.")
                    
                    import base64
                    with open(path, "rb") as f:
                        content_bytes = f.read()
                        b64_content = base64.b64encode(content_bytes).decode("utf-8")
                        
                    message["attachments"].append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": os.path.basename(path),
                        "contentBytes": b64_content
                    })

        payload = {
            "message": message,
            "saveToSentItems": "true"
        }

        response = requests.post(url, headers=self._get_headers(), json=payload)
        
        status = "Failed"
        error_msg = None
        
        if response.status_code == 202:
            print("Email sent successfully.")
            status = "Sent"
            success = True
        else:
            print(f"Error sending email: {response.text}")
            error_msg = response.text
            success = False

        # Log to Database
        if SessionLocal:
            session = SessionLocal()
            try:
                log = EmailLog(
                    Recipient=",".join(to_email) if isinstance(to_email, list) else to_email,
                    FromEmail=self.user_email,
                    Subject=subject,
                    Status=status,
                    ErrorMessage=error_msg
                )
                session.add(log)
                session.commit()
            except Exception as e:
                print(f"Failed to save email log: {e}")
            finally:
                session.close()
        
        return success
