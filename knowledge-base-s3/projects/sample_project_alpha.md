# 過去案件: Sample Project Alpha

## 案件概要

Sample Project Alphaは、社内向けWebアプリケーションをAWSへ新規構築した案件である。

本番環境と開発環境を構築し、本番環境は2つのAvailability Zoneを使用した。

## 構成

- Application Load Balancer: 1台
- EC2: 本番環境4台、開発環境1台
- RDS for PostgreSQL: 本番環境1DB、開発環境1DB
- CloudWatchアラーム: 12個

本番環境のEC2はApplication Load Balancer配下に配置した。

本番環境のRDSはMulti-AZ構成とし、バックアップ保持期間を14日間に設定した。

## 実績工数

- 基本設計: 6.0人日
- 詳細設計: 8.0人日
- 構築: 7.0人日
- 単体テスト: 5.0人日
- 合計: 26.0人日

## 見積前提

- AWSアカウントとネットワーク接続は顧客から提供される。
- アプリケーション開発とデータ移行は対象外とする。
- 作業は平日日中に実施する。

## 振り返り

CloudWatchアラームの追加要望が設計完了後に発生したため、当初見積もりより1.0人日の追加工数が生じた。
