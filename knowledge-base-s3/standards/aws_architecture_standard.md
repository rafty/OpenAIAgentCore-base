# AWS標準アーキテクチャ

## EC2

本番環境では原則として2つ以上のAvailability Zoneを利用する。

WebサーバーはApplication Load Balancer配下に配置する。

EC2への直接SSH接続は禁止し、
AWS Systems Manager Session Managerを使用する。

## RDS

本番環境のRDSは原則Multi-AZ構成とする。

バックアップ保持期間は14日間とする。
